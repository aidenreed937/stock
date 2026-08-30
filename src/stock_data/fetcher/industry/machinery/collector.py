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
from stock_data.fetcher.industry.models import ConstructionMachineryRecord

logger = logging.getLogger(__name__)


class MachineryCollector:
    """工程机械 (挖掘机产销/小松挖机开工小时) 采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.machinery_dir = self.raw_dir / "machinery"

    def collect(self) -> list[ConstructionMachineryRecord]:
        """执行工程机械数据采集: 检查真实 RAW 快照 -> 校验落盘。"""
        self.machinery_dir.mkdir(parents=True, exist_ok=True)
        for candidate in ["excavator_real.csv", "excavator_monthly.csv"]:
            raw_csv = self.machinery_dir / candidate
            if raw_csv.exists():
                return self.load_from_raw_csv(raw_csv)

        return []

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
                        source=row.get("source") or "CCMA",
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
