"""中国创新药海外 License-out (BD) 底账解析、月度时序聚合与持久化模块。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.pharma.models import (
    PharmaBdAssetRecord,
    PharmaBdDealRecord,
    PharmaBdEventRecord,
    PharmaLicenseOutRecord,
)

logger = logging.getLogger(__name__)

PHARMA_CSV_FIELDNAMES = [
    "report_month",
    "trade_date",
    "upfront_cash_million_usd",
    "potential_total_deal_million_usd",
    "monthly_upfront_million_usd",
    "monthly_total_deal_million_usd",
    "deal_count",
    "asset_count",
    "mnc_deal_count",
    "global_deal_count",
    "median_upfront_million_usd",
    "avg_upfront_million_usd",
    "upfront_to_total_ratio",
    "global_rights_ratio",
    "mnc_ratio",
    "late_stage_ratio",
    "adc_asset_count",
    "bispecific_asset_count",
    "metabolic_glp1_asset_count",
    "small_molecule_asset_count",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "null"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_deals_ledger_data(
    raw_deals: list[dict[str, Any]],
) -> tuple[list[PharmaBdDealRecord], list[PharmaBdAssetRecord], list[PharmaBdEventRecord]]:
    """从 YAML 字典列表解析标准化 Deals、Assets、Events 领域记录。"""
    deals: list[PharmaBdDealRecord] = []
    assets: list[PharmaBdAssetRecord] = []
    events: list[PharmaBdEventRecord] = []

    for d in raw_deals:
        deal_id = str(d["deal_id"]).strip()
        ann_date = date.fromisoformat(str(d["announcement_date"]).strip())
        eff_date = (
            date.fromisoformat(str(d["effective_date"]).strip())
            if d.get("effective_date")
            else ann_date
        )
        deals.append(
            PharmaBdDealRecord(
                deal_id=deal_id,
                licensor=str(d.get("licensor", "")),
                licensor_type=str(d.get("licensor_type") or ""),
                licensee=str(d.get("licensee", "")),
                is_mnc=bool(d.get("is_mnc", False)),
                transaction_type=str(d.get("transaction_type") or "license_out"),
                territory_scope=str(d.get("territory_scope") or ""),
                announcement_date=ann_date,
                effective_date=eff_date,
                source_filing=str(d.get("source_filing", "")),
                source_url=str(d.get("source_url", "")),
            )
        )
        for a in d.get("assets", []):
            assets.append(
                PharmaBdAssetRecord(
                    asset_id=str(a.get("asset_id", f"AST-{deal_id}")).strip(),
                    deal_id=deal_id,
                    drug_name_code=str(a.get("drug_name_code", "")),
                    target=str(a.get("target", "")),
                    modality=str(a.get("modality") or ""),
                    stage=str(a.get("stage") or ""),
                    indication=str(a.get("indication", "")),
                )
            )
        for ev in d.get("events", []):
            ev_date = date.fromisoformat(str(ev.get("event_date", ann_date.isoformat())).strip())
            events.append(
                PharmaBdEventRecord(
                    event_id=str(ev.get("event_id", f"EVT-{deal_id}")).strip(),
                    deal_id=deal_id,
                    event_type=str(ev.get("event_type") or ""),
                    event_date=ev_date,
                    upfront_cash_usd=_optional_float(ev.get("upfront_cash_usd")),
                    equity_investment_usd=_optional_float(ev.get("equity_investment_usd")),
                    option_payment_usd=_optional_float(ev.get("option_payment_usd")),
                    near_term_milestone_usd=_optional_float(ev.get("near_term_milestone_usd")),
                    potential_total_deal_usd=_optional_float(ev.get("potential_total_deal_usd")),
                    equity_stake_pct=float(ev["equity_stake_pct"])
                    if ev.get("equity_stake_pct") is not None
                    else None,
                    original_currency=str(ev.get("original_currency") or ""),
                    notes=str(ev.get("notes", "")),
                )
            )

    return deals, assets, events


def _make_pharma_record(
    m_str: str,
    t_date: date,
    rel_date: date | None,
    now_iso: str,
    upfront_sum: float | None = None,
    potential_sum: float | None = None,
    deal_cnt: int = 0,
    all_assets_cnt: int = 0,
    mnc_cnt: int = 0,
    global_cnt: int = 0,
    median_upfront: float | None = None,
    avg_upfront: float | None = None,
    adc_cnt: int = 0,
    bisp_cnt: int = 0,
    glp1_cnt: int = 0,
    small_cnt: int = 0,
    late_stage_cnt: int = 0,
) -> PharmaLicenseOutRecord:
    """构建标准化 PharmaLicenseOutRecord 记录。"""
    return PharmaLicenseOutRecord(
        report_month=m_str,
        trade_date=t_date,
        upfront_cash_million_usd=round(upfront_sum, 2) if upfront_sum is not None else None,
        potential_total_deal_million_usd=round(potential_sum, 2)
        if potential_sum is not None
        else None,
        deal_count=deal_cnt,
        asset_count=all_assets_cnt,
        mnc_deal_count=mnc_cnt,
        global_deal_count=global_cnt,
        median_upfront_million_usd=round(median_upfront, 2) if median_upfront is not None else None,
        avg_upfront_million_usd=round(avg_upfront, 2) if avg_upfront is not None else None,
        upfront_to_total_ratio=round(upfront_sum / potential_sum, 4)
        if upfront_sum is not None and potential_sum is not None and potential_sum > 0
        else None,
        global_rights_ratio=round(global_cnt / deal_cnt, 4) if deal_cnt > 0 else None,
        mnc_ratio=round(mnc_cnt / deal_cnt, 4) if deal_cnt > 0 else None,
        late_stage_ratio=round(late_stage_cnt / all_assets_cnt, 4) if all_assets_cnt > 0 else None,
        adc_asset_count=adc_cnt,
        bispecific_asset_count=bisp_cnt,
        metabolic_glp1_asset_count=glp1_cnt,
        small_molecule_asset_count=small_cnt,
        unit="million_usd",
        source="PharmaCube/Filings/PR",
        source_url="http://www.cninfo.com.cn",
        release_date=rel_date,
        data_status="actual",
        collected_at=now_iso,
        monthly_upfront_million_usd=round(upfront_sum, 2) if upfront_sum is not None else None,
        monthly_total_deal_million_usd=round(potential_sum, 2)
        if potential_sum is not None
        else None,
    )


def aggregate_events_to_monthly(
    deals: list[PharmaBdDealRecord],
    assets: list[PharmaBdAssetRecord],
    events: list[PharmaBdEventRecord],
) -> list[PharmaLicenseOutRecord]:
    """将底层交易事件直接聚合为月度特征事实。"""
    deal_map = {d.deal_id: d for d in deals}
    deal_assets_map: dict[str, list[PharmaBdAssetRecord]] = {}
    for a in assets:
        deal_assets_map.setdefault(a.deal_id, []).append(a)

    month_events: dict[str, list[PharmaBdEventRecord]] = {}
    for ev in events:
        month_events.setdefault(ev.event_date.strftime("%Y-%m"), []).append(ev)

    now_iso = now_utc_iso()
    records: list[PharmaLicenseOutRecord] = []

    for m_str in sorted(month_events):
        yr, mo = parse_month_string(m_str)
        t_date = get_month_end_date(yr, mo)

        ev_list = month_events[m_str]
        rel_date = max(e.event_date for e in ev_list)
        upfront_values = [e.upfront_cash_usd for e in ev_list if e.upfront_cash_usd is not None]
        potential_values = [
            e.potential_total_deal_usd for e in ev_list if e.potential_total_deal_usd is not None
        ]
        upfront_sum = sum(upfront_values) / 1e6 if upfront_values else None
        potential_sum = sum(potential_values) / 1e6 if potential_values else None
        upfront_list = [v / 1e6 for v in upfront_values if v > 0]
        median_upfront = sorted(upfront_list)[len(upfront_list) // 2] if upfront_list else None
        avg_upfront = sum(upfront_list) / len(upfront_list) if upfront_list else None

        deal_ids = list({e.deal_id for e in ev_list})
        deal_cnt = len(deal_ids)
        mnc_cnt = sum(1 for did in deal_ids if deal_map.get(did) and deal_map[did].is_mnc)
        global_cnt = sum(
            1
            for did in deal_ids
            if deal_map.get(did) and deal_map[did].territory_scope in ["global", "global_ex_china"]
        )

        adc_cnt, bisp_cnt, glp1_cnt, small_cnt, late_stage_cnt, all_assets_cnt = 0, 0, 0, 0, 0, 0
        for did in deal_ids:
            ast_list = deal_assets_map.get(did, [])
            all_assets_cnt += len(ast_list)
            for a in ast_list:
                if a.modality == "adc":
                    adc_cnt += 1
                elif a.modality == "bispecific":
                    bisp_cnt += 1
                elif "glp-1" in a.target.lower() or a.modality == "metabolic":
                    glp1_cnt += 1
                elif a.modality == "small_molecule":
                    small_cnt += 1
                if a.stage in ["phase_2", "phase_3", "approved"]:
                    late_stage_cnt += 1

        records.append(
            _make_pharma_record(
                m_str=m_str,
                t_date=t_date,
                rel_date=rel_date,
                now_iso=now_iso,
                upfront_sum=upfront_sum,
                potential_sum=potential_sum,
                deal_cnt=deal_cnt,
                all_assets_cnt=all_assets_cnt,
                mnc_cnt=mnc_cnt,
                global_cnt=global_cnt,
                median_upfront=median_upfront,
                avg_upfront=avg_upfront,
                adc_cnt=adc_cnt,
                bisp_cnt=bisp_cnt,
                glp1_cnt=glp1_cnt,
                small_cnt=small_cnt,
                late_stage_cnt=late_stage_cnt,
            )
        )

    records.sort(key=lambda r: r.trade_date)
    return records


def save_pharma_raw_csv(file_path: Path | str, records: list[PharmaLicenseOutRecord]) -> None:
    """持久化 RAW 快照 CSV。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PHARMA_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_month": r.report_month,
                    "trade_date": r.trade_date.isoformat(),
                    "upfront_cash_million_usd": r.upfront_cash_million_usd
                    if r.upfront_cash_million_usd is not None
                    else "",
                    "potential_total_deal_million_usd": r.potential_total_deal_million_usd
                    if r.potential_total_deal_million_usd is not None
                    else "",
                    "monthly_upfront_million_usd": r.monthly_upfront_million_usd
                    if r.monthly_upfront_million_usd is not None
                    else "",
                    "monthly_total_deal_million_usd": r.monthly_total_deal_million_usd
                    if r.monthly_total_deal_million_usd is not None
                    else "",
                    "deal_count": r.deal_count,
                    "asset_count": r.asset_count,
                    "mnc_deal_count": r.mnc_deal_count,
                    "global_deal_count": r.global_deal_count,
                    "median_upfront_million_usd": r.median_upfront_million_usd
                    if r.median_upfront_million_usd is not None
                    else "",
                    "avg_upfront_million_usd": r.avg_upfront_million_usd
                    if r.avg_upfront_million_usd is not None
                    else "",
                    "upfront_to_total_ratio": r.upfront_to_total_ratio
                    if r.upfront_to_total_ratio is not None
                    else "",
                    "global_rights_ratio": r.global_rights_ratio
                    if r.global_rights_ratio is not None
                    else "",
                    "mnc_ratio": r.mnc_ratio if r.mnc_ratio is not None else "",
                    "late_stage_ratio": r.late_stage_ratio
                    if r.late_stage_ratio is not None
                    else "",
                    "adc_asset_count": r.adc_asset_count,
                    "bispecific_asset_count": r.bispecific_asset_count,
                    "metabolic_glp1_asset_count": r.metabolic_glp1_asset_count,
                    "small_molecule_asset_count": r.small_molecule_asset_count,
                    "unit": r.unit,
                    "source": r.source,
                    "source_url": r.source_url,
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status,
                    "collected_at": r.collected_at,
                }
            )


def load_pharma_raw_csv(file_path: Path | str) -> list[PharmaLicenseOutRecord]:
    """从创新药 BD RAW 快照 CSV 中读取并标准化。"""
    p = Path(file_path)
    if not p.exists():
        return []

    def _safe_int(val: Any) -> int:
        try:
            return int(float(str(val).strip())) if val is not None and str(val).strip() else 0
        except (ValueError, TypeError):
            return 0

    records: list[PharmaLicenseOutRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            month_str = row["report_month"].strip()
            year, month = parse_month_string(month_str)
            t_date = get_month_end_date(year, month)
            rel_date = date.fromisoformat(row["release_date"]) if row.get("release_date") else None
            upfront_c = _optional_float(row.get("upfront_cash_million_usd"))
            if upfront_c is None:
                upfront_c = _optional_float(row.get("monthly_upfront_million_usd"))
            total_c = _optional_float(row.get("potential_total_deal_million_usd"))
            if total_c is None:
                total_c = _optional_float(row.get("monthly_total_deal_million_usd"))

            records.append(
                _make_pharma_record(
                    m_str=month_str,
                    t_date=t_date,
                    rel_date=rel_date,
                    now_iso=row.get("collected_at") or now_utc_iso(),
                    upfront_sum=upfront_c,
                    potential_sum=total_c,
                    deal_cnt=_safe_int(row.get("deal_count")),
                    all_assets_cnt=_safe_int(row.get("asset_count")),
                    mnc_cnt=_safe_int(row.get("mnc_deal_count")),
                    global_cnt=_safe_int(row.get("global_deal_count")),
                    median_upfront=_optional_float(row.get("median_upfront_million_usd")),
                    avg_upfront=_optional_float(row.get("avg_upfront_million_usd")),
                    adc_cnt=_safe_int(row.get("adc_asset_count")),
                    bisp_cnt=_safe_int(row.get("bispecific_asset_count")),
                    glp1_cnt=_safe_int(row.get("metabolic_glp1_asset_count")),
                    small_cnt=_safe_int(row.get("small_molecule_asset_count")),
                    late_stage_cnt=_safe_int(row.get("late_stage_ratio")),
                )
            )
    records.sort(key=lambda r: r.trade_date)
    return records
