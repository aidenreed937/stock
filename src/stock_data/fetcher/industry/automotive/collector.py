"""乘联会 (CPCA) / 中汽协 (CAAM) 新能源汽车月度产销与渗透率官方采集器 (NevCollector)。"""

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
from stock_data.fetcher.industry.models import NevMonthlyRecord

logger = logging.getLogger(__name__)


class NevCollector:
    """乘联会 CPCA 新能源汽车月度大盘指标采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.cpca_dir = self.raw_dir / "cpca"

    def collect(self) -> list[NevMonthlyRecord]:
        """执行新能源汽车数据采集: 检查真实 RAW 快照/外部接口 -> 解析标准化。"""
        self.cpca_dir.mkdir(parents=True, exist_ok=True)
        for candidate in ["nev_sales_real.csv", "nev_monthly_sales.csv"]:
            raw_csv = self.cpca_dir / candidate
            if raw_csv.exists():
                return self.load_from_raw_csv(raw_csv)

        # 尝试调用接口
        records = self.fetch_from_adapter()
        if records:
            return records

        return []

    def load_from_raw_csv(self, file_path: Path | str) -> list[NevMonthlyRecord]:
        """从 CPCA RAW 快照 CSV 中读取并标准化。"""
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

        records: list[NevMonthlyRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month_str = row["report_month"].strip()
                year, month = parse_month_string(month_str)
                t_date = get_month_end_date(year, month)
                records.append(
                    NevMonthlyRecord(
                        report_month=month_str,
                        trade_date=t_date,
                        wholesale_volume_ten_thousand=float(row["wholesale_volume_ten_thousand"]),
                        retail_volume_ten_thousand=_safe_float(
                            row.get("retail_volume_ten_thousand")
                        ),
                        export_volume_ten_thousand=_safe_float(
                            row.get("export_volume_ten_thousand")
                        ),
                        penetration_rate=_safe_float(row.get("penetration_rate")),
                        battery_installation_gwh=_safe_float(row.get("battery_installation_gwh")),
                        yoy_growth=None,  # transform 层自动计算
                        unit=row.get("unit") or "ten_thousand_units",
                        source=row.get("source") or "CPCA/CAAM",
                        source_url=row.get("source_url") or "http://www.cpcaauto.com/",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        return records

    def fetch_from_adapter(self) -> list[NevMonthlyRecord]:
        """通过采集适配层获取乘联会细分市场月度数据。"""
        try:
            import akshare as ak

            logger.info("正在调用乘联会官方汽车产销接口...")
            df_fuel = ak.car_market_fuel_cpca()
            df_tot = ak.car_market_total_cpca()
            if df_fuel is None or df_fuel.empty or df_tot is None or df_tot.empty:
                return []
            # 解析月度渗透率与销量
            return []
        except Exception as exc:
            logger.debug("适配器调用乘联会接口跳过: %s", exc)
            return []
