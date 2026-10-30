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
from stock_data.fetcher.industry.machinery.models import ConstructionMachineryRecord

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
        """执行工程机械数据采集: 在线爬取 CCMA/Komatsu 最新数据并落盘，以最新采集为准。"""
        self.machinery_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.machinery_dir / "excavator_monthly.csv"
        cached_records = self.load_from_raw_csv(csv_file)
        cached_by_month = {record.report_month: record for record in cached_records}

        # 在线爬取 CCMA 协会销售快报与小松 Komtrax 开工小时
        ccma_sales = self.ccma_crawler.fetch_latest_sales()
        komatsu_hours = self.komatsu_crawler.fetch_latest_hours()

        all_months = set(cached_by_month) | set(ccma_sales.keys()) | set(komatsu_hours.keys())
        now_iso = now_utc_iso()

        records: list[ConstructionMachineryRecord] = []
        for m_str in sorted(all_months):
            yr, mo = parse_month_string(m_str)
            t_date = get_month_end_date(yr, mo)
            cached = cached_by_month.get(m_str)
            ccma_item = ccma_sales.get(m_str)
            hrs_val = komatsu_hours.get(m_str)

            if ccma_item is None and hrs_val is None and cached is not None:
                records.append(cached)
                continue

            tot_u = (
                ccma_item.get("excavator_total_units")
                if ccma_item and ccma_item.get("excavator_total_units") is not None
                else cached.excavator_total_units
                if cached
                else None
            )
            dom_u = (
                ccma_item.get("excavator_domestic_units")
                if ccma_item and ccma_item.get("excavator_domestic_units") is not None
                else cached.excavator_domestic_units
                if cached
                else None
            )
            exp_u = (
                ccma_item.get("excavator_export_units")
                if ccma_item and ccma_item.get("excavator_export_units") is not None
                else cached.excavator_export_units
                if cached
                else None
            )
            rel_d = (
                ccma_item.get("release_date")
                if ccma_item and isinstance(ccma_item.get("release_date"), date)
                else cached.release_date
                if cached
                else None
            )
            s_url = (
                ccma_item.get("source_url")
                if ccma_item and ccma_item.get("source_url")
                else cached.source_url
                if cached
                else "http://www.cncma.org/"
            )

            records.append(
                ConstructionMachineryRecord(
                    report_month=m_str,
                    trade_date=t_date,
                    excavator_total_units=tot_u,
                    excavator_domestic_units=dom_u,
                    excavator_export_units=exp_u,
                    komatsu_hours_china=hrs_val
                    if hrs_val is not None
                    else cached.komatsu_hours_china
                    if cached
                    else None,
                    komatsu_hours_yoy=cached.komatsu_hours_yoy if cached else None,
                    export_ratio=cached.export_ratio if cached else None,
                    excavator_total_3mma=cached.excavator_total_3mma if cached else None,
                    yoy_growth=cached.yoy_growth if cached else None,
                    yoy_growth_3mma=cached.yoy_growth_3mma if cached else None,
                    mom_growth_3mma=cached.mom_growth_3mma if cached else None,
                    unit=cached.unit if cached else "units/hours",
                    source=str(
                        ccma_item.get("source")
                        if ccma_item
                        else cached.source
                        if cached
                        else "CCMA/Komatsu"
                    ),
                    source_url=str(s_url),
                    release_date=rel_d,
                    data_status=str(
                        ccma_item.get("data_status")
                        if ccma_item
                        else cached.data_status
                        if cached
                        else "actual"
                    ),
                    collected_at=now_iso
                    if ccma_item or hrs_val is not None
                    else cached.collected_at
                    if cached
                    else now_iso,
                )
            )

        if not records:
            logger.warning("在线抓取工程机械数据失败")
            return []

        final_records = sorted(records, key=lambda r: r.trade_date)
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
                tot = _safe_float(row.get("total_sales_volume")) or _safe_float(
                    row.get("excavator_total_units")
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
                        excavator_domestic_units=dom,
                        excavator_export_units=exp,
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
