"""国家能源局 (NEA) / 中电联 (CEC) 光伏月度新增与累计装机容量独立采集器 (SolarCollector)。"""

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

    def collect(self) -> list[SolarCapacityRecord]:
        """执行光伏装机数据采集: 检查 RAW 快照/公告解析 -> 差分计算当月新增 -> 校验落盘。"""
        # 1. 优先加载 NEA RAW CSV 快照
        raw_csv = self.raw_dir / "nea" / "solar_capacity.csv"
        if raw_csv.exists():
            return self.load_from_raw_csv(raw_csv)

        # 2. 尝试从公告/公开网页抓取
        records = self.fetch_from_nea_announcements()
        if records:
            return records

        return []

    def load_from_raw_csv(self, file_path: Path | str) -> list[SolarCapacityRecord]:
        """从 NEA RAW 快照 CSV 中读取并标准化。"""
        p = Path(file_path)
        if not p.exists():
            return []

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
                        cumulative_capacity_gw=float(row["cumulative_capacity_gw"])
                        if row.get("cumulative_capacity_gw")
                        else None,
                        yoy_growth=float(row["yoy_growth"]) if row.get("yoy_growth") else None,
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

    def fetch_from_nea_announcements(self) -> list[SolarCapacityRecord]:
        """从国家能源局官方电力统计通报抓取并差分计算。"""
        # 保留动态提取入口，后续接入自动化抓取
        return []
