"""海关总署 (GACC) 光通信收发模块出口金额与数量独立采集器 (OpticalModuleCollector)。"""

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import OpticalModuleExportRecord

logger = logging.getLogger(__name__)


class OpticalModuleCollector:
    """海关总署 (GACC) 光通信收发模块出口月度数据采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)

    def collect(self) -> list[OpticalModuleExportRecord]:
        """执行光通信模块出口数据采集: 检查 RAW 快照 -> 校验落盘。"""
        raw_csv = self.raw_dir / "customs" / "optical_module_export.csv"
        if raw_csv.exists():
            return self.load_from_raw_csv(raw_csv)

        logger.warning("未找到海关光通信模块出口 RAW 快照: %s", raw_csv)
        return []

    def load_from_raw_csv(self, file_path: Path | str) -> list[OpticalModuleExportRecord]:
        """从海关光模块 RAW 快照 CSV 中读取并标准化。"""
        p = Path(file_path)
        if not p.exists():
            return []

        records: list[OpticalModuleExportRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month_str = row["report_month"].strip()
                year, month = parse_month_string(month_str)
                t_date = get_month_end_date(year, month)
                records.append(
                    OpticalModuleExportRecord(
                        report_month=month_str,
                        trade_date=t_date,
                        export_value_million_usd=float(row["export_value_million_usd"]),
                        export_volume_ten_thousand=float(row["export_volume_ten_thousand"])
                        if row.get("export_volume_ten_thousand")
                        else None,
                        export_asp_usd=float(row["export_asp_usd"])
                        if row.get("export_asp_usd")
                        else None,
                        export_value_3mma=float(row["export_value_3mma"])
                        if row.get("export_value_3mma")
                        else None,
                        yoy_growth=float(row["yoy_growth"]) if row.get("yoy_growth") else None,
                        yoy_growth_3mma=float(row["yoy_growth_3mma"])
                        if row.get("yoy_growth_3mma")
                        else None,
                        mom_growth_3mma=float(row["mom_growth_3mma"])
                        if row.get("mom_growth_3mma")
                        else None,
                        unit=row.get("unit") or "million_usd",
                        source=row.get("source") or "GACC",
                        source_url=row.get("source_url") or "http://stats.customs.gov.cn/",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        logger.info("海关光通信模块出口 RAW 快照加载成功: 共 %d 个月度记录", len(records))
        return records
