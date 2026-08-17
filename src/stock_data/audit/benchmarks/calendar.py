"""宏观与财务周期事实基准提供者 (月频与季频连续序列基准)。"""

from __future__ import annotations

from datetime import date

import polars as pl

from stock_data.audit.benchmarks.base import BenchmarkProvider


class MacroCalendarBenchmarkProvider(BenchmarkProvider):
    """宏观月度/季度连续序列事实基准。"""

    def __init__(self, frequency: str = "monthly") -> None:
        self.frequency = frequency.lower()

    def get_expected_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        """生成指定日期范围内的自然月份 (YYYYMM) 或季度 (YYYYQn) 期望序列。"""
        if self.frequency == "monthly":
            months: list[str] = []
            cur_year, cur_month = start_date.year, start_date.month
            end_year, end_month = end_date.year, end_date.month

            while (cur_year < end_year) or (cur_year == end_year and cur_month <= end_month):
                months.append(f"{cur_year}{cur_month:02d}")
                cur_month += 1
                if cur_month > 12:
                    cur_month = 1
                    cur_year += 1

            return pl.DataFrame(
                {
                    "symbol": ["MACRO"] * len(months),
                    "trade_date": months,
                }
            )

        # 季度基准 (0331, 0630, 0930, 1231)
        quarters: list[str] = []
        for y in range(start_date.year, end_date.year + 1):
            for q_end in ["0331", "0630", "0930", "1231"]:
                d_str = f"{y}{q_end}"
                d_val = date(y, int(q_end[:2]), int(q_end[2:]))
                if start_date <= d_val <= end_date:
                    quarters.append(d_str)

        return pl.DataFrame(
            {
                "symbol": ["MACRO"] * len(quarters),
                "trade_date": quarters,
            }
        )
