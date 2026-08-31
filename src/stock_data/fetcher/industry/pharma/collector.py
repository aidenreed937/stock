"""中国创新药海外 License-out (BD) 交易与实体层统一采集器 (PharmaBdCollector)。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.pharma.crawler import PharmaAnnouncementCrawler
from stock_data.fetcher.industry.pharma.models import (
    PharmaBdAssetRecord,
    PharmaBdDealRecord,
    PharmaBdEventRecord,
    PharmaLicenseOutRecord,
)
from stock_data.fetcher.industry.pharma.transform import (
    assets_to_frame,
    deals_to_frame,
    events_to_frame,
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
    "adc_deal_count",
    "bispecific_deal_count",
    "metabolic_glp1_deal_count",
    "small_molecule_deal_count",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


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
        deal_rec = PharmaBdDealRecord(
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
        deals.append(deal_rec)

        for a in d.get("assets", []):
            asset_id = str(a.get("asset_id", f"AST-{deal_id}")).strip()
            assets.append(
                PharmaBdAssetRecord(
                    asset_id=asset_id,
                    deal_id=deal_id,
                    drug_name_code=str(a.get("drug_name_code", "")),
                    target=str(a.get("target", "")),
                    modality=str(a.get("modality", "small_molecule")),
                    stage=str(a.get("stage", "phase_2")),
                    indication=str(a.get("indication", "")),
                )
            )

        for ev in d.get("events", []):
            ev_id = str(ev.get("event_id", f"EVT-{deal_id}")).strip()
            ev_date = date.fromisoformat(str(ev.get("event_date", ann_date.isoformat())).strip())
            events.append(
                PharmaBdEventRecord(
                    event_id=ev_id,
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
        m_str = ev.event_date.strftime("%Y-%m")
        month_events.setdefault(m_str, []).append(ev)

    now_iso = now_utc_iso()
    records: list[PharmaLicenseOutRecord] = []

    for m_str in sorted(month_events.keys()):
        ev_list = month_events[m_str]
        yr, mo = parse_month_string(m_str)
        t_date = get_month_end_date(yr, mo)

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

        adc_cnt, bisp_cnt, glp1_cnt, small_cnt = 0, 0, 0, 0
        late_stage_cnt, all_assets_cnt = 0, 0

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
            PharmaLicenseOutRecord(
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
                upfront_to_total_ratio=round(upfront_sum / potential_sum, 4)
                if potential_sum > 0
                else 0.0,
                global_rights_ratio=round(global_cnt / deal_cnt, 4) if deal_cnt > 0 else 0.0,
                mnc_ratio=round(mnc_cnt / deal_cnt, 4) if deal_cnt > 0 else 0.0,
                late_stage_ratio=round(late_stage_cnt / all_assets_cnt, 4)
                if all_assets_cnt > 0
                else 0.0,
                adc_deal_count=adc_cnt,
                bispecific_deal_count=bisp_cnt,
                metabolic_glp1_deal_count=glp1_cnt,
                small_molecule_deal_count=small_cnt,
                unit="million_usd",
                source="PharmaCube/Filings/PR",
                source_url="http://www.cninfo.com.cn",
                release_date=t_date,
                data_status="actual",
                collected_at=now_iso,
                monthly_upfront_million_usd=round(upfront_sum, 2),
                monthly_total_deal_million_usd=round(potential_sum, 2),
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
                    "adc_deal_count": r.adc_deal_count,
                    "bispecific_deal_count": r.bispecific_deal_count,
                    "metabolic_glp1_deal_count": r.metabolic_glp1_deal_count,
                    "small_molecule_deal_count": r.small_molecule_deal_count,
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

    def _safe_float(val: Any) -> float | None:
        if val is None or str(val).strip() == "":
            return None
        try:
            return float(str(val).strip())
        except (ValueError, TypeError):
            return None

    def _safe_int(val: Any) -> int:
        if val is None or str(val).strip() == "":
            return 0
        try:
            return int(float(str(val).strip()))
        except (ValueError, TypeError):
            return 0

    records: list[PharmaLicenseOutRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            month_str = row["report_month"].strip()
            year, month = parse_month_string(month_str)
            t_date = get_month_end_date(year, month)
            upfront_c = (
                _safe_float(row.get("upfront_cash_million_usd"))
                or _safe_float(row.get("monthly_upfront_million_usd"))
                or 0.0
            )
            total_c = (
                _safe_float(row.get("potential_total_deal_million_usd"))
                or _safe_float(row.get("monthly_total_deal_million_usd"))
                or 0.0
            )

            records.append(
                PharmaLicenseOutRecord(
                    report_month=month_str,
                    trade_date=t_date,
                    upfront_cash_million_usd=upfront_c,
                    potential_total_deal_million_usd=total_c,
                    deal_count=_safe_int(row.get("deal_count")),
                    asset_count=_safe_int(row.get("asset_count")),
                    mnc_deal_count=_safe_int(row.get("mnc_deal_count")),
                    global_deal_count=_safe_int(row.get("global_deal_count")),
                    median_upfront_million_usd=_safe_float(row.get("median_upfront_million_usd")),
                    avg_upfront_million_usd=_safe_float(row.get("avg_upfront_million_usd")),
                    upfront_to_total_ratio=_safe_float(row.get("upfront_to_total_ratio")),
                    upfront_3mma=_safe_float(row.get("upfront_3mma")),
                    total_deal_3mma=_safe_float(row.get("total_deal_3mma")),
                    yoy_growth_3mma=_safe_float(row.get("yoy_growth_3mma")),
                    mom_growth_3mma=_safe_float(row.get("mom_growth_3mma")),
                    global_rights_ratio=_safe_float(row.get("global_rights_ratio")),
                    mnc_ratio=_safe_float(row.get("mnc_ratio")),
                    late_stage_ratio=_safe_float(row.get("late_stage_ratio")),
                    adc_deal_count=_safe_int(row.get("adc_deal_count")),
                    bispecific_deal_count=_safe_int(row.get("bispecific_deal_count")),
                    metabolic_glp1_deal_count=_safe_int(row.get("metabolic_glp1_deal_count")),
                    small_molecule_deal_count=_safe_int(row.get("small_molecule_deal_count")),
                    unit=row.get("unit") or "million_usd",
                    source=row.get("source") or "PharmaCube/Filings/PR",
                    source_url=row.get("source_url") or "",
                    release_date=date.fromisoformat(row["release_date"])
                    if row.get("release_date")
                    else None,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                    monthly_upfront_million_usd=upfront_c,
                    monthly_total_deal_million_usd=total_c,
                )
            )
    records.sort(key=lambda r: r.trade_date)
    return records


class PharmaBdCollector:
    """中国创新药海外 License-out (BD) 交易采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        processed_dir: Path | str = "data/processed/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.pharma_dir = self.raw_dir / "pharma"
        self.processed_dir = Path(processed_dir)
        self.crawler = PharmaAnnouncementCrawler(raw_dir=self.raw_dir)

    def collect(self) -> list[PharmaLicenseOutRecord]:
        """执行创新药出海 BD 数据采集: 在线检索最新公告并落盘，以最新采集为准。"""
        self.pharma_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = self.pharma_dir / "deals_ledger.yaml"

        # 在线爬取 A/H 股交易所最新对外许可公告
        live_deals = self.crawler.fetch_latest_deals()
        if not live_deals:
            logger.warning("在线抓取创新药出海 BD 公告失败")
            return []

        # 以最新在线采集结果为准，覆盖落盘底账
        data: dict[str, Any] = {"deals": live_deals}
        with ledger_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        logger.info("在线采集创新药出海 BD 公告 %d 笔并覆盖落盘底账", len(live_deals))

        return self.process_ledger_deals(data["deals"])

    def process_ledger_deals(self, raw_deals: list[dict[str, Any]]) -> list[PharmaLicenseOutRecord]:
        """解析结构化交易底账，落盘 Processed 实体层与 RAW 快照。"""
        deals, assets, events = parse_deals_ledger_data(raw_deals)

        # 落盘 Processed 实体层
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        deals_to_frame(deals).write_parquet(self.processed_dir / "pharma_bd_deals.parquet")
        assets_to_frame(assets).write_parquet(self.processed_dir / "pharma_bd_assets.parquet")
        events_to_frame(events).write_parquet(self.processed_dir / "pharma_bd_events.parquet")
        logger.info(
            "已落盘 Processed 实体层: %d 笔 Deals, %d 条 Assets, %d 个 Events",
            len(deals),
            len(assets),
            len(events),
        )

        records = aggregate_events_to_monthly(deals, assets, events)
        self.save_to_raw_csv(self.pharma_dir / "license_out_monthly.csv", records)
        return records

    def load_from_ledger_yaml(self, file_path: Path | str) -> list[PharmaLicenseOutRecord]:
        """从外部指定 YAML 底账文件解析并处理。"""
        p = Path(file_path)
        if not p.exists():
            return []
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return self.process_ledger_deals(data.get("deals", []))

    def save_to_raw_csv(self, file_path: Path | str, records: list[PharmaLicenseOutRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_pharma_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[PharmaLicenseOutRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_pharma_raw_csv(file_path)
