"""工程机械行业月度产销与小松开工小时数采集器 (MachineryCollector)。"""

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
    """中国工程机械工业协会 (CCMA) 与小松挖掘机开工小时数采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)

    def collect(self) -> list[ConstructionMachineryRecord]:
        """执行工程机械月度数据采集: 检查 RAW 快照 -> 校验落盘。"""
        raw_csv = self.raw_dir / "machinery" / "excavator_monthly.csv"
        if raw_csv.exists():
            return self.load_from_raw_csv(raw_csv)

        logger.warning("未找到工程机械月度 RAW 快照: %s", raw_csv)
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
                records.append(
                    ConstructionMachineryRecord(
                        report_month=month_str,
                        trade_date=t_date,
                        excavator_total_units=float(row["excavator_total_units"]),
                        excavator_domestic_units=float(row["excavator_domestic_units"]),
                        excavator_export_units=float(row["excavator_export_units"]),
                        komatsu_hours_china=_safe_float(row.get("komatsu_hours_china")),
                        komatsu_hours_yoy=_safe_float(row.get("komatsu_hours_yoy")),
                        export_ratio=_safe_float(row.get("export_ratio")),
                        excavator_total_3mma=_safe_float(row.get("excavator_total_3mma")),
                        yoy_growth=_safe_float(row.get("yoy_growth")),
                        yoy_growth_3mma=_safe_float(row.get("yoy_growth_3mma")),
                        mom_growth_3mma=_safe_float(row.get("mom_growth_3mma")),
                        unit=row.get("unit") or "units/hours",
                        source=row.get("source") or "CCMA/Komatsu",
                        source_url=row.get("source_url") or "",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        logger.info("工程机械产销与小松工时 RAW 快照加载成功: 共 %d 个月度记录", len(records))
        return records
