"""中国创新药海外 License-out (BD) 交易月度首付款与总额官方采集器 (PharmaBdCollector)。"""

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
from stock_data.fetcher.industry.models import PharmaLicenseOutRecord

logger = logging.getLogger(__name__)


class PharmaBdCollector:
    """中国创新药海外 License-out (BD) 交易月度汇总采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.pharma_dir = self.raw_dir / "pharma"

    def collect(self) -> list[PharmaLicenseOutRecord]:
        """执行创新药出海 BD 交易数据采集: 检查真实 RAW 快照 -> 校验落盘。"""
        self.pharma_dir.mkdir(parents=True, exist_ok=True)
        for candidate in ["license_out_real.csv", "license_out_monthly.csv"]:
            raw_csv = self.pharma_dir / candidate
            if raw_csv.exists():
                return self.load_from_raw_csv(raw_csv)

        return []

    def load_from_raw_csv(self, file_path: Path | str) -> list[PharmaLicenseOutRecord]:
        """从创新药 BD RAW 快照 CSV 中读取并标准化。"""
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

        records: list[PharmaLicenseOutRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month_str = row["report_month"].strip()
                year, month = parse_month_string(month_str)
                t_date = get_month_end_date(year, month)
                records.append(
                    PharmaLicenseOutRecord(
                        report_month=month_str,
                        trade_date=t_date,
                        monthly_upfront_million_usd=float(row["monthly_upfront_million_usd"]),
                        monthly_total_deal_million_usd=float(row["monthly_total_deal_million_usd"]),
                        deal_count=int(row["deal_count"]),
                        upfront_3mma=None,  # transform 层自动计算 3MMA 与 YoY
                        yoy_growth_3mma=None,
                        unit=row.get("unit") or "million_usd",
                        source=row.get("source") or "Company_Announcements",
                        source_url=row.get("source_url") or "",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        return records
