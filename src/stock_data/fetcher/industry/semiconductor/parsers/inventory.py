"""半导体 IDM 库存 RAW CSV 解析器。"""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.semiconductor.models import SemiconductorInventoryRecord

SEC_FINANCIAL_FORMS = frozenset({"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "6-K"})


@dataclass(frozen=True)
class SecFiling:
    """SEC submissions 中可用于发布日期匹配的财务申报记录。"""

    form: str
    filing_date: date
    report_date: date | None
    primary_document: str
    size: int = 0
    accession_number: str = ""


def load_inventory_raw_csv(
    file_path: Path | str,
    release_dates: Mapping[tuple[str, str], date] | None = None,
) -> list[SemiconductorInventoryRecord]:
    """从 IDM 财报 RAW CSV 读取并构造库存记录模型。"""
    p = Path(file_path)
    if not p.exists():
        return []

    records: list[SemiconductorInventoryRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            report_quarter = row["report_quarter"].strip().upper()
            symbol = row["symbol"].strip().upper()
            inventory_raw = _source_text(row.get("inventory_usd"))
            cost_raw = _source_text(row.get("cost_of_revenue_usd"))
            release_date_raw = (row.get("release_date") or "").strip()
            source_period_end_raw = (row.get("source_period_end") or "").strip()
            release_date = (
                date.fromisoformat(release_date_raw)
                if release_date_raw
                else (release_dates or {}).get((symbol, report_quarter))
            )
            records.append(
                SemiconductorInventoryRecord(
                    symbol=symbol,
                    report_quarter=report_quarter,
                    trade_date=date.fromisoformat(row["trade_date"].strip()),
                    inventory_usd_million=_parse_required_float(inventory_raw, "inventory_usd"),
                    cost_of_revenue_usd_million=_parse_required_float(
                        cost_raw, "cost_of_revenue_usd"
                    ),
                    unit=(row.get("unit") or "million_usd").strip(),
                    source=(row.get("source") or "SEC_EDGAR_10Q_10K_20F_6K").strip(),
                    source_url=(row.get("source_url") or "").strip(),
                    release_date=release_date,
                    data_status=(row.get("data_status") or "actual").strip(),
                    collected_at=(row.get("collected_at") or "").strip(),
                    inventory_usd_raw=inventory_raw,
                    cost_of_revenue_usd_raw=cost_raw,
                    source_period_end=(
                        date.fromisoformat(source_period_end_raw) if source_period_end_raw else None
                    ),
                    fiscal_period=(row.get("fiscal_period_raw") or "").strip(),
                    raw_content_sha256=(row.get("raw_content_sha256") or "").strip(),
                    raw_snapshot_path=(row.get("raw_snapshot_path") or "").strip(),
                    cost_of_revenue_annual_raw=_source_text(row.get("cost_of_revenue_annual_raw")),
                    cost_of_revenue_derivation=(
                        row.get("cost_of_revenue_derivation") or ""
                    ).strip(),
                )
            )

    return records


def _source_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_required_float(value: str | None, field: str) -> float:
    if value is None:
        raise ValueError(f"Inventory RAW 字段 {field} 为空")
    try:
        number = float(value.replace(",", "").replace("$", ""))
    except ValueError as exc:
        raise ValueError(f"Inventory RAW 字段 {field} 不是数值: {value}") from exc
    if not math.isfinite(number):
        raise ValueError(f"Inventory RAW 字段 {field} 不是有限数值: {value}")
    return number


def extract_sec_filings(payload: Mapping[str, Any]) -> list[SecFiling]:
    """从 SEC submissions 响应提取财务申报的官方 filingDate。"""
    section = _submission_section(payload)
    forms = section.get("form", [])
    filing_dates = section.get("filingDate", [])
    report_dates = section.get("reportDate", [])
    documents = section.get("primaryDocument", [])
    sizes = section.get("size", [])
    accessions = section.get("accessionNumber", [])

    filings: list[SecFiling] = []
    for index, raw_form in enumerate(forms):
        form = str(raw_form or "").strip().upper()
        if form not in SEC_FINANCIAL_FORMS:
            continue
        filing_date = _parse_iso_date(_item_at(filing_dates, index))
        if filing_date is None:
            continue
        filings.append(
            SecFiling(
                form=form,
                filing_date=filing_date,
                report_date=_parse_iso_date(_item_at(report_dates, index)),
                primary_document=str(_item_at(documents, index) or ""),
                size=_parse_int(_item_at(sizes, index)),
                accession_number=str(_item_at(accessions, index) or ""),
            )
        )
    return filings


def build_inventory_release_date_map(
    rows: Sequence[Mapping[str, object]],
    filings_by_symbol: Mapping[str, Sequence[SecFiling]],
) -> dict[tuple[str, str], date]:
    """按库存行的观测日匹配 SEC 财务申报日。

    `trade_date` 仅用于在相邻季度申报之间选择对应财报，不会被写入结果作为
    `release_date`。匹配不到官方申报日的记录会被留空，交由 RAW 契约拒绝落盘。
    """
    result: dict[tuple[str, str], date] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        report_quarter = str(row.get("report_quarter") or "").strip()
        trade_date = _parse_iso_date(row.get("trade_date"))
        if not symbol or not report_quarter or trade_date is None:
            continue

        candidates = [
            filing
            for filing in filings_by_symbol.get(symbol, ())
            if _is_inventory_filing(symbol, filing)
        ]
        if not candidates:
            continue

        regular_candidates = [
            filing for filing in candidates if filing.form in {"10-Q", "10-K", "10-Q/A", "10-K/A"}
        ]
        if symbol == "STM":
            nearest = _match_foreign_quarterly_filing(candidates, trade_date)
        elif symbol == "NXPI":
            # NXP switched from 6-K interim reports to 10-Q; use the latter once
            # a report-date match is available, and the old 6-K path otherwise.
            nearest = _match_report_date_filing(
                regular_candidates,
                trade_date,
                max_gap_days=45,
                prefer_nearest=True,
            )
            if nearest is None:
                nearest = _match_foreign_quarterly_filing(candidates, trade_date)
        else:
            nearest = _match_report_date_filing(candidates, trade_date)
        if nearest is not None:
            result[(symbol, report_quarter)] = nearest.filing_date
    return result


def _submission_section(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    filings = payload.get("filings")
    if isinstance(filings, Mapping):
        recent = filings.get("recent")
        if isinstance(recent, Mapping):
            return recent
    recent = payload.get("recent")
    if isinstance(recent, Mapping):
        return recent
    return payload


def _item_at(values: object, index: int) -> object:
    if isinstance(values, Sequence) and not isinstance(values, str) and index < len(values):
        return values[index]
    return None


def _is_inventory_filing(symbol: str, filing: SecFiling) -> bool:
    if filing.form != "6-K":
        return True
    return symbol in {"STM", "NXPI"}


def _match_foreign_quarterly_filing(
    candidates: Sequence[SecFiling],
    trade_date: date,
) -> SecFiling | None:
    """匹配旧版外国发行人 6-K 季度业绩申报。

    旧 SEC submissions 的部分 6-K `reportDate` 等于提交日，不能按该字段匹配。
    季度业绩 6-K 在季度结束后发布；只在 10~60 天窗口内选取较完整的财务申报，
    以排除 AGM、投资者活动等临近日期的无关 6-K。
    """
    lower = trade_date.toordinal() + 10
    upper = trade_date.toordinal() + 60
    window = [
        filing
        for filing in candidates
        if filing.form == "6-K" and lower <= filing.filing_date.toordinal() <= upper
    ]
    if not window:
        return None

    substantial = [filing for filing in window if filing.size >= 250_000]
    ranked = substantial or window
    return min(ranked, key=lambda filing: (filing.filing_date, -filing.size))


def _match_report_date_filing(
    candidates: Sequence[SecFiling],
    trade_date: date,
    *,
    max_gap_days: int = 120,
    prefer_nearest: bool = False,
) -> SecFiling | None:
    """按申报中的报告期匹配 10-Q/10-K 等财务申报。"""
    dated = [filing for filing in candidates if filing.report_date is not None]
    if not dated:
        return None

    if prefer_nearest:
        nearest = min(
            dated,
            key=lambda filing: abs((_filing_report_date(filing) - trade_date).days),
        )
        reference_date = _filing_report_date(nearest)
        ranked = [filing for filing in dated if _filing_report_date(filing) == reference_date]
    else:
        before = [filing for filing in dated if _filing_report_date(filing) <= trade_date]
        if before:
            reference_date = max(_filing_report_date(filing) for filing in before)
            ranked = [filing for filing in before if _filing_report_date(filing) == reference_date]
        else:
            reference_date = min(_filing_report_date(filing) for filing in dated)
            ranked = [filing for filing in dated if _filing_report_date(filing) == reference_date]

    if abs((reference_date - trade_date).days) > max_gap_days:
        return None
    return min(ranked, key=lambda filing: (_form_priority(filing.form), filing.filing_date))


def _form_priority(form: str) -> int:
    if form in {"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F"}:
        return 0
    return 1


def _filing_report_date(filing: SecFiling) -> date:
    if filing.report_date is None:
        raise ValueError("SEC filing 缺少 report_date")
    return filing.report_date


def _parse_iso_date(value: object) -> date | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _parse_int(value: object) -> int:
    try:
        return int(str(value).strip()) if value is not None else 0
    except ValueError:
        return 0
