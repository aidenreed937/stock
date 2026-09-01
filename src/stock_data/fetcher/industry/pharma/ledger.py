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


def compute_next_month_end(trade_date: date) -> date:
    """计算次月月末日期（作为出海 BD 官方披露的保守生效日）。"""
    if trade_date.month == 12:
        return get_month_end_date(trade_date.year + 1, 1)
    return get_month_end_date(trade_date.year, trade_date.month + 1)


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
                licensor_type=str(d.get("licensor_type", "listed_hk")),
                licensee=str(d.get("licensee", "")),
                is_mnc=bool(d.get("is_mnc", False)),
                transaction_type=str(d.get("transaction_type", "license_out")),
                territory_scope=str(d.get("territory_scope", "global_ex_china")),
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
                    modality=str(a.get("modality", "small_molecule")),
                    stage=str(a.get("stage", "phase_2")),
                    indication=str(a.get("indication", "")),
                )
            )
        for ev in d.get("events", []):
            ev_date = date.fromisoformat(str(ev.get("event_date", ann_date.isoformat())).strip())
            events.append(
                PharmaBdEventRecord(
                    event_id=str(ev.get("event_id", f"EVT-{deal_id}")).strip(),
                    deal_id=deal_id,
                    event_type=str(ev.get("event_type", "initial_deal")),
                    event_date=ev_date,
                    upfront_cash_usd=float(ev.get("upfront_cash_usd", 0.0)),
                    equity_investment_usd=float(ev.get("equity_investment_usd", 0.0)),
                    option_payment_usd=float(ev.get("option_payment_usd", 0.0)),
                    near_term_milestone_usd=float(ev.get("near_term_milestone_usd", 0.0)),
                    potential_total_deal_usd=float(ev.get("potential_total_deal_usd", 0.0)),
                    equity_stake_pct=float(ev["equity_stake_pct"])
                    if ev.get("equity_stake_pct") is not None
                    else None,
                    original_currency=str(ev.get("original_currency", "USD")),
                    notes=str(ev.get("notes", "")),
                )
            )

    return deals, assets, events


def _make_pharma_record(
    m_str: str,
    t_date: date,
    rel_date: date,
    now_iso: str,
    upfront_sum: float = 0.0,
    potential_sum: float = 0.0,
    deal_cnt: int = 0,
    all_assets_cnt: int = 0,
    mnc_cnt: int = 0,
    global_cnt: int = 0,
    median_upfront: float = 0.0,
    avg_upfront: float = 0.0,
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
        upfront_cash_million_usd=round(upfront_sum, 2),
        potential_total_deal_million_usd=round(potential_sum, 2),
        deal_count=deal_cnt,
        asset_count=all_assets_cnt,
        mnc_deal_count=mnc_cnt,
        global_deal_count=global_cnt,
        median_upfront_million_usd=round(median_upfront, 2),
        avg_upfront_million_usd=round(avg_upfront, 2),
        upfront_to_total_ratio=round(upfront_sum / potential_sum, 4) if potential_sum > 0 else 0.0,
        global_rights_ratio=round(global_cnt / deal_cnt, 4) if deal_cnt > 0 else 0.0,
        mnc_ratio=round(mnc_cnt / deal_cnt, 4) if deal_cnt > 0 else 0.0,
        late_stage_ratio=round(late_stage_cnt / all_assets_cnt, 4) if all_assets_cnt > 0 else 0.0,
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
        monthly_upfront_million_usd=round(upfront_sum, 2),
        monthly_total_deal_million_usd=round(potential_sum, 2),
    )


def aggregate_events_to_monthly(
    deals: list[PharmaBdDealRecord],
    assets: list[PharmaBdAssetRecord],
    events: list[PharmaBdEventRecord],
) -> list[PharmaLicenseOutRecord]:
    """将底层交易事件直接聚合为月度特征事实，并生成 2020-01 至 2026-08 完整连续月度序列。"""
    deal_map = {d.deal_id: d for d in deals}
    deal_assets_map: dict[str, list[PharmaBdAssetRecord]] = {}
    for a in assets:
        deal_assets_map.setdefault(a.deal_id, []).append(a)

    month_events: dict[str, list[PharmaBdEventRecord]] = {}
    for ev in events:
        month_events.setdefault(ev.event_date.strftime("%Y-%m"), []).append(ev)

    all_months: list[str] = []
    curr_yr, curr_mo = 2020, 1
    end_yr, end_mo = 2026, 8
    while (curr_yr < end_yr) or (curr_yr == end_yr and curr_mo <= end_mo):
        all_months.append(f"{curr_yr:04d}-{curr_mo:02d}")
        curr_yr, curr_mo = (curr_yr + 1, 1) if curr_mo == 12 else (curr_yr, curr_mo + 1)

    now_iso = now_utc_iso()
    records: list[PharmaLicenseOutRecord] = []

    for m_str in all_months:
        yr, mo = parse_month_string(m_str)
        t_date = get_month_end_date(yr, mo)
        rel_date = compute_next_month_end(t_date)

        if m_str not in month_events:
            records.append(_make_pharma_record(m_str, t_date, rel_date, now_iso))
            continue

        ev_list = month_events[m_str]
        upfront_sum = sum(e.upfront_cash_usd for e in ev_list) / 1e6
        potential_sum = sum(e.potential_total_deal_usd for e in ev_list) / 1e6
        upfront_list = [e.upfront_cash_usd / 1e6 for e in ev_list if e.upfront_cash_usd > 0]
        median_upfront = (
            sorted(upfront_list)[len(upfront_list) // 2]
            if upfront_list
            else (upfront_sum / len(ev_list) if ev_list else 0.0)
        )
        avg_upfront = upfront_sum / len(ev_list) if ev_list else 0.0

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
                    "upfront_cash_million_usd": r.upfront_cash_million_usd,
                    "potential_total_deal_million_usd": r.potential_total_deal_million_usd,
                    "monthly_upfront_million_usd": r.upfront_cash_million_usd,
                    "monthly_total_deal_million_usd": r.potential_total_deal_million_usd,
                    "deal_count": r.deal_count,
                    "asset_count": r.asset_count,
                    "mnc_deal_count": r.mnc_deal_count,
                    "global_deal_count": r.global_deal_count,
                    "median_upfront_million_usd": r.median_upfront_million_usd or "",
                    "avg_upfront_million_usd": r.avg_upfront_million_usd or "",
                    "upfront_to_total_ratio": r.upfront_to_total_ratio or "",
                    "global_rights_ratio": r.global_rights_ratio or "",
                    "mnc_ratio": r.mnc_ratio or "",
                    "late_stage_ratio": r.late_stage_ratio or "",
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

    def _safe_float(val: Any) -> float:
        try:
            return float(str(val).strip()) if val is not None and str(val).strip() else 0.0
        except (ValueError, TypeError):
            return 0.0

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
            rel_date = (
                date.fromisoformat(row["release_date"])
                if row.get("release_date")
                else compute_next_month_end(t_date)
            )
            upfront_c = _safe_float(row.get("upfront_cash_million_usd")) or _safe_float(
                row.get("monthly_upfront_million_usd")
            )
            total_c = _safe_float(row.get("potential_total_deal_million_usd")) or _safe_float(
                row.get("monthly_total_deal_million_usd")
            )

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
                    median_upfront=_safe_float(row.get("median_upfront_million_usd")),
                    avg_upfront=_safe_float(row.get("avg_upfront_million_usd")),
                    adc_cnt=_safe_int(row.get("adc_asset_count")),
                    bisp_cnt=_safe_int(row.get("bispecific_asset_count")),
                    glp1_cnt=_safe_int(row.get("metabolic_glp1_asset_count")),
                    small_cnt=_safe_int(row.get("small_molecule_asset_count")),
                    late_stage_cnt=_safe_int(row.get("late_stage_ratio")),
                )
            )
    records.sort(key=lambda r: r.trade_date)
    return records
