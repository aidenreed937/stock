"""中国工程机械工业协会 (CCMA) 挖掘机月度销量与小松开工小时数官方采集器 (MachineryCollector)。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.machinery.crawler import (
    CcmaCrawler,
    KomatsuCrawler,
)
from stock_data.fetcher.industry.models import ConstructionMachineryRecord

logger = logging.getLogger(__name__)


class MachineryCollector:
    """工程机械 (挖掘机产销/小松挖机开工小时) 双源协同采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.machinery_dir = self.raw_dir / "machinery"
        self.ccma_crawler = CcmaCrawler(raw_dir=self.raw_dir)
        self.komatsu_crawler = KomatsuCrawler(raw_dir=self.raw_dir)

    def collect(self) -> list[ConstructionMachineryRecord]:
        """执行工程机械数据采集: 检查真实 RAW 快照 -> 在线增量爬取 -> 协同合并落盘。"""
        self.machinery_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.machinery_dir / "excavator_monthly.csv"
        alt_file = self.machinery_dir / "excavator_real.csv"

        records_map: dict[str, ConstructionMachineryRecord] = {}
        for candidate in [alt_file, csv_file]:
            if candidate.exists():
                for rec in self.load_from_raw_csv(candidate):
                    records_map[rec.report_month] = rec

        # 2. 在线增量爬取 CCMA 协会销售快报与小松 Komtrax 开工小时
        ccma_sales = self.ccma_crawler.fetch_latest_sales()
        komatsu_hours = self.komatsu_crawler.fetch_latest_hours()

        has_new_data = False
        all_months = set(records_map.keys()) | set(ccma_sales.keys()) | set(komatsu_hours.keys())
        now_iso = now_utc_iso()

        for m_str in all_months:
            yr, mo = parse_month_string(m_str)
            t_date = get_month_end_date(yr, mo)
            existing = records_map.get(m_str)

            ccma_item = ccma_sales.get(m_str)
            hrs_val = komatsu_hours.get(m_str)

            if existing:
                # 补全或更新已有记录
                new_tot = (
                    ccma_item["excavator_total_units"]
                    if ccma_item and ccma_item.get("excavator_total_units")
                    else existing.excavator_total_units
                )
                new_dom = (
                    ccma_item["excavator_domestic_units"]
                    if ccma_item and ccma_item.get("excavator_domestic_units")
                    else existing.excavator_domestic_units
                )
                new_exp = (
                    ccma_item["excavator_export_units"]
                    if ccma_item and ccma_item.get("excavator_export_units")
                    else existing.excavator_export_units
                )
                new_hrs = hrs_val if hrs_val is not None else existing.komatsu_hours_china
                new_rel = (
                    ccma_item["release_date"]
                    if ccma_item and isinstance(ccma_item.get("release_date"), date)
                    else existing.release_date
                )

                if (
                    new_tot != existing.excavator_total_units
                    or new_hrs != existing.komatsu_hours_china
                ):
                    has_new_data = True

                records_map[m_str] = ConstructionMachineryRecord(
                    report_month=m_str,
                    trade_date=t_date,
                    excavator_total_units=new_tot,
                    excavator_domestic_units=new_dom,
                    excavator_export_units=new_exp,
                    komatsu_hours_china=new_hrs,
                    komatsu_hours_yoy=None,
                    export_ratio=None,
                    excavator_total_3mma=None,
                    yoy_growth=None,
                    yoy_growth_3mma=None,
                    mom_growth_3mma=None,
                    unit=existing.unit or "units/hours",
                    source="CCMA/Komatsu",
                    source_url=existing.source_url or "http://www.cncma.org/",
                    release_date=new_rel,
                    data_status="actual",
                    collected_at=existing.collected_at or now_iso,
                )
            else:
                # 全新月份入库
                has_new_data = True
                tot_u = ccma_item.get("excavator_total_units", 0.0) if ccma_item else 0.0
                dom_u = ccma_item.get("excavator_domestic_units", 0.0) if ccma_item else 0.0
                exp_u = ccma_item.get("excavator_export_units", 0.0) if ccma_item else 0.0
                rel_d = (
                    ccma_item.get("release_date")
                    if ccma_item and isinstance(ccma_item.get("release_date"), date)
                    else None
                )
                s_url = ccma_item.get("source_url") if ccma_item else "http://www.cncma.org/"

                records_map[m_str] = ConstructionMachineryRecord(
                    report_month=m_str,
                    trade_date=t_date,
                    excavator_total_units=tot_u,
                    excavator_domestic_units=dom_u,
                    excavator_export_units=exp_u,
                    komatsu_hours_china=hrs_val,
                    komatsu_hours_yoy=None,
                    export_ratio=None,
                    excavator_total_3mma=None,
                    yoy_growth=None,
                    yoy_growth_3mma=None,
                    mom_growth_3mma=None,
                    unit="units/hours",
                    source="CCMA/Komatsu",
                    source_url=str(s_url),
                    release_date=rel_d,
                    data_status="actual",
                    collected_at=now_iso,
                )

        final_records = sorted(records_map.values(), key=lambda r: r.trade_date)

        # 3. 若有新增或变更，写回更新 RAW CSV
        if has_new_data and final_records:
            self.save_to_raw_csv(csv_file, final_records)

        return final_records

    def save_to_raw_csv(
        self, file_path: Path | str, records: list[ConstructionMachineryRecord]
    ) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "report_month",
            "trade_date",
            "excavator_total_units",
            "excavator_domestic_units",
            "excavator_export_units",
            "komatsu_hours_china",
            "unit",
            "source",
            "source_url",
            "release_date",
            "data_status",
            "collected_at",
        ]
        with p.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                writer.writerow(
                    {
                        "report_month": r.report_month,
                        "trade_date": r.trade_date.isoformat(),
                        "excavator_total_units": r.excavator_total_units,
                        "excavator_domestic_units": r.excavator_domestic_units,
                        "excavator_export_units": r.excavator_export_units,
                        "komatsu_hours_china": r.komatsu_hours_china
                        if r.komatsu_hours_china is not None
                        else "",
                        "unit": r.unit or "units/hours",
                        "source": r.source or "CCMA/Komatsu",
                        "source_url": r.source_url or "http://www.cncma.org/",
                        "release_date": r.release_date.isoformat() if r.release_date else "",
                        "data_status": r.data_status or "actual",
                        "collected_at": r.collected_at or now_utc_iso(),
                    }
                )

    def load_from_raw_csv(self, file_path: Path | str) -> list[ConstructionMachineryRecord]:
        """从工程机械 RAW 快照 CSV 中读取并标准化。"""
        p = Path(file_path)
        if not p.exists():
            return []

        def _safe_float(val: str | None) -> float | None:
            if not val or not val.strip():
                return None
            try:
                return float(val.strip())
            except (ValueError, TypeError):
                return None

        records: list[ConstructionMachineryRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month_str = row["report_month"].strip()
                year, month = parse_month_string(month_str)
                t_date = get_month_end_date(year, month)
                tot = (
                    _safe_float(row.get("total_sales_volume"))
                    or _safe_float(row.get("excavator_total_units"))
                    or 0.0
                )
                dom = _safe_float(row.get("domestic_sales_volume")) or _safe_float(
                    row.get("excavator_domestic_units")
                )
                exp = _safe_float(row.get("export_sales_volume")) or _safe_float(
                    row.get("excavator_export_units")
                )
                hrs = _safe_float(row.get("komatsu_operating_hours")) or _safe_float(
                    row.get("komatsu_hours_china")
                )

                records.append(
                    ConstructionMachineryRecord(
                        report_month=month_str,
                        trade_date=t_date,
                        excavator_total_units=tot,
                        excavator_domestic_units=dom or 0.0,
                        excavator_export_units=exp or 0.0,
                        komatsu_hours_china=hrs,
                        komatsu_hours_yoy=None,
                        export_ratio=None,
                        excavator_total_3mma=None,
                        yoy_growth=None,  # transform 层自动计算
                        yoy_growth_3mma=None,
                        mom_growth_3mma=None,
                        unit=row.get("unit") or "units/hours",
                        source=row.get("source") or "CCMA/Komatsu",
                        source_url=row.get("source_url") or "http://www.cncma.org/",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        return records
