"""Avnet/Arrow 渠道库存 SEC companyfacts 解析器。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

SEC_CHANNEL_FORMS = frozenset({"10-Q", "10-K", "10-Q/A", "10-K/A"})
INVENTORY_CONCEPTS = ("InventoryNet",)
COST_OF_REVENUE_CONCEPTS = ("CostOfRevenue",)


def parse_channel_inventory_companyfacts(
    payload: Mapping[str, Any],
    *,
    company: str,
    symbol: str,
    source_url: str,
    collected_at: str,
    raw_content_hash: str,
    raw_snapshot_path: str,
) -> list[dict[str, Any]]:
    """从 SEC companyfacts JSON 提取渠道商季度库存与季度营业成本源端字段。

    10-K 财年 Q4（年报季）的 CostOfRevenue 在 companyfacts 中只有全年 duration（~365 天）
    条目，没有 70-110 天季度条目；直接用季度匹配会整行丢失（2024Q2/Q4 交替缺失的根因）。
    因此对 10-K 行改用差分法：Q4 单季 COGS = 全年 COGS −（财年内前三季 COGS 之和）。
    """
    inventory_items = _concept_usd_items(payload, INVENTORY_CONCEPTS)
    all_cost_items = _concept_usd_items(payload, COST_OF_REVENUE_CONCEPTS)
    quarterly_cost = _quarterly_duration_items(all_cost_items)
    annual_cost = _annual_duration_items(all_cost_items)
    cost_by_accession = _latest_items_by_key(quarterly_cost, "accn")
    cost_by_end = _latest_items_by_key(quarterly_cost, "end")

    rows: list[dict[str, Any]] = []
    for inventory_item in inventory_items:
        form = _source_text(inventory_item.get("form")).upper()
        if form not in SEC_CHANNEL_FORMS:
            continue
        end_date = _parse_iso_date(inventory_item.get("end"))
        if end_date is None:
            continue
        if _source_text(inventory_item.get("val")) == "":
            continue

        accession = _source_text(inventory_item.get("accn"))
        cost_item = cost_by_accession.get(accession) if accession else None
        if cost_item is None or _parse_iso_date(cost_item.get("end")) != end_date:
            cost_item = cost_by_end.get(end_date.isoformat())
        if cost_item is None or _source_text(cost_item.get("val")) == "":
            # 10-K 财年 Q4：季度条目不存在，用全年 COGS 差分求单季
            cost_item = _derive_q4_cost(quarterly_cost, annual_cost, end_date)
        if cost_item is None or _source_text(cost_item.get("val")) == "":
            continue

        release_date = _parse_iso_date(inventory_item.get("filed"))
        if release_date is None:
            release_date = _parse_iso_date(cost_item.get("filed"))

        rows.append(
            {
                "company": company,
                "symbol": symbol.upper(),
                "report_quarter": _report_quarter(inventory_item, cost_item, end_date),
                "trade_date": end_date,
                "fiscal_year_raw": _source_text(inventory_item.get("fy")),
                "fiscal_period_raw": _source_text(inventory_item.get("fp")),
                "inventory_usd_raw": _source_text(inventory_item.get("val")),
                "cost_of_revenue_usd_raw": _source_text(cost_item.get("val")),
                "form_raw": form,
                "accession_raw": accession,
                "source": "SEC_companyfacts",
                "source_url": source_url,
                "release_date": release_date,
                "data_status": "actual",
                "collected_at": collected_at,
                "raw_content_sha256": raw_content_hash,
                "raw_snapshot_path": raw_snapshot_path,
            }
        )

    return _dedupe_rows(rows)


def _concept_usd_items(
    payload: Mapping[str, Any],
    concepts: Sequence[str],
) -> list[Mapping[str, Any]]:
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        return []
    namespace = facts.get("us-gaap")
    if not isinstance(namespace, Mapping):
        return []

    items: list[Mapping[str, Any]] = []
    for concept in concepts:
        concept_payload = namespace.get(concept)
        if not isinstance(concept_payload, Mapping):
            continue
        units = concept_payload.get("units")
        if not isinstance(units, Mapping):
            continue
        usd_items = units.get("USD")
        if not isinstance(usd_items, Sequence) or isinstance(usd_items, str):
            continue
        items.extend(item for item in usd_items if isinstance(item, Mapping))
    return items


def _quarterly_duration_items(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for item in items:
        form = _source_text(item.get("form")).upper()
        if form not in SEC_CHANNEL_FORMS:
            continue
        start_date = _parse_iso_date(item.get("start"))
        end_date = _parse_iso_date(item.get("end"))
        if start_date is None or end_date is None:
            continue
        duration_days = (end_date - start_date).days + 1
        if 70 <= duration_days <= 110:
            result.append(item)
    return result


def _annual_duration_items(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """筛选全年 duration（~365 天）的 CostOfRevenue 条目（10-K 年报口径）。"""
    result: list[Mapping[str, Any]] = []
    for item in items:
        form = _source_text(item.get("form")).upper()
        if form not in SEC_CHANNEL_FORMS:
            continue
        start_date = _parse_iso_date(item.get("start"))
        end_date = _parse_iso_date(item.get("end"))
        if start_date is None or end_date is None:
            continue
        duration_days = (end_date - start_date).days + 1
        if 300 <= duration_days <= 400:
            result.append(item)
    return result


def _derive_q4_cost(
    quarterly_cost: Sequence[Mapping[str, Any]],
    annual_cost: Sequence[Mapping[str, Any]],
    end_date: date,
) -> Mapping[str, Any] | None:
    """10-K 财年 Q4 单季 COGS 差分：全年 COGS −（财年内前三季 COGS 之和）。

    10-K 的 CostOfRevenue 只有全年 duration 条目；其财年 Q4 的季度 COGS 需用
    全年值减去该财年内 Q1+Q2+Q3 的季度值得到（Q4 = FY − ΣQ1..Q3）。
    返回带 ``val``/``filed`` 的伪 cost item；财年内季度不足 3 个或差分非正时返回 None。
    """
    annual = None
    for item in annual_cost:
        if _parse_iso_date(item.get("end")) == end_date:
            annual = item
            break
    if annual is None:
        return None

    annual_start = _parse_iso_date(annual.get("start"))
    if annual_start is None:
        return None
    # 财年内（start ≥ 财年起点、end < 财年 Q4 end）的季度条目，按 end 升序取前 3
    quarters = []
    for item in quarterly_cost:
        q_start = _parse_iso_date(item.get("start"))
        q_end = _parse_iso_date(item.get("end"))
        if q_start is None or q_end is None:
            continue
        if q_start < annual_start or q_end >= end_date:
            continue
        quarters.append((q_end, _source_text(item.get("val"))))
    quarters.sort(key=lambda pair: pair[0])
    if len(quarters) < 3:
        return None

    try:
        annual_val = float(_source_text(annual.get("val")))
        prior_sum = sum(float(val) for _, val in quarters[-3:])
    except ValueError:
        return None
    q4_val = annual_val - prior_sum
    if q4_val <= 0:
        return None
    return {"val": f"{q4_val:.0f}", "filed": annual.get("filed"), "end": end_date.isoformat()}


def _latest_items_by_key(
    items: Sequence[Mapping[str, Any]],
    key: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in sorted(items, key=_item_sort_key):
        raw_key = _source_text(item.get(key))
        if raw_key:
            result[raw_key] = item
    return result


def _dedupe_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 (symbol, report_quarter) 去重，保留**最早披露日**（release_date 最小）。

    同一季度在 companyfacts 中可能多次出现（原始 10-K + 后续文件重述同一财年 Q4），
    黄金表取首次披露版本：release_date 代表数据最早可用的无前视生效日。
    """
    earliest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in sorted(rows, key=_row_sort_key):
        key = (str(row["symbol"]), str(row["report_quarter"]))
        if key not in earliest:
            earliest[key] = row
    return sorted(earliest.values(), key=lambda row: (row["trade_date"], row["symbol"]))


def _item_sort_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _source_text(item.get("end")),
        _source_text(item.get("filed")),
        _source_text(item.get("accn")),
    )


def _row_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    release_date = row.get("release_date")
    release_text = release_date.isoformat() if isinstance(release_date, date) else ""
    return (
        str(row.get("trade_date") or ""),
        release_text,
        str(row.get("accession_raw") or ""),
    )


def _report_quarter(
    inventory_item: Mapping[str, Any],
    cost_item: Mapping[str, Any],
    end_date: date,
) -> str:
    for item in (inventory_item, cost_item):
        frame = _source_text(item.get("frame"))
        match = re.search(r"CY(20\d\d)Q([1-4])", frame)
        if match:
            return f"{match.group(1)}Q{match.group(2)}"
    return _calendar_report_quarter(end_date)


def _calendar_report_quarter(value: date) -> str:
    shifted = value - timedelta(days=15)
    quarter = (shifted.month - 1) // 3 + 1
    year = shifted.year
    return f"{year}Q{quarter}"


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


def _source_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
