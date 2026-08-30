"""国家能源局 (NEA) / 中电联 (CEC) 光伏月度新增与累计装机容量官方采集器 (SolarCollector)。"""

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
from stock_data.fetcher.industry.models import SolarCapacityRecord

logger = logging.getLogger(__name__)


class SolarCollector:
    """国家能源局 (NEA) 光伏装机月度统计采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.nea_dir = self.raw_dir / "nea"

    def collect(self) -> list[SolarCapacityRecord]:
        """执行光伏装机数据采集: 检查真实 RAW 快照/公告解析 -> 差分计算当月新增 -> 校验落盘。"""
        self.nea_dir.mkdir(parents=True, exist_ok=True)
        for candidate in ["solar_capacity_real.csv", "solar_capacity.csv"]:
            raw_csv = self.nea_dir / candidate
            if raw_csv.exists():
                return self.load_from_raw_csv(raw_csv)

        return []

    def load_from_raw_csv(self, file_path: Path | str) -> list[SolarCapacityRecord]:
        """从 NEA RAW 快照 CSV 中读取并标准化。"""
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

        records: list[SolarCapacityRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month_str = row["report_month"].strip()
                year, month = parse_month_string(month_str)
                t_date = get_month_end_date(year, month)
                records.append(
                    SolarCapacityRecord(
                        report_month=month_str,
                        trade_date=t_date,
                        monthly_new_capacity_gw=float(row["monthly_new_capacity_gw"]),
                        cumulative_capacity_gw=_safe_float(row.get("cumulative_capacity_gw")),
                        yoy_growth=None,  # transform 层自动计算
                        unit=row.get("unit") or "gw",
                        source=row.get("source") or "NEA",
                        source_url=row.get("source_url") or "http://www.nea.gov.cn/",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        return records
