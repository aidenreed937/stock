"""中观行业日频事实基准提供者 (申万 2021 一级 31 / 二级 134 行业基准)。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock.data.audit.benchmarks.base import BenchmarkProvider, get_trading_calendar

if TYPE_CHECKING:
    from stock.data.catalog import DataCatalog


# 申万 2021 官方一级 31 行业标准代码集合
SW_L1_INDUSTRY_CODES: list[str] = [
    "801010.SI", "801030.SI", "801040.SI", "801050.SI", "801080.SI",
    "801110.SI", "801120.SI", "801130.SI", "801140.SI", "801150.SI",
    "801160.SI", "801170.SI", "801180.SI", "801200.SI", "801210.SI",
    "801230.SI", "801710.SI", "801720.SI", "801730.SI", "801740.SI",
    "801750.SI", "801760.SI", "801770.SI", "801780.SI", "801790.SI",
    "801880.SI", "801890.SI", "801950.SI", "801960.SI", "801970.SI",
    "801980.SI",
]


class IndustryDailyBenchmarkProvider(BenchmarkProvider):
    """申万行业日频事实基准提供者。

    预期集合公式: Expected(t) = TradingCalendar(t) × SW_L1_Codes(31)
    """

    def __init__(
        self,
        catalog: DataCatalog | None = None,
        level: str = "L1",
    ) -> None:
        self.level = level.upper()
        if catalog is None:
            from stock.data.catalog import DataCatalog

            self.catalog = DataCatalog(data_source="tushare")
        else:
            self.catalog = catalog

    def get_expected_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        """根据交易日历与申万 31 行业列表生成预期主键全集。"""
        trading_dates = get_trading_calendar(start_date=start_date, end_date=end_date)
        if not trading_dates:
            return pl.DataFrame(
                {
                    "symbol": pl.Series([], dtype=pl.Utf8),
                    "trade_date": pl.Series([], dtype=pl.Utf8),
                }
            )

        dates_str = [d.strftime("%Y%m%d") for d in trading_dates]
        codes = SW_L1_INDUSTRY_CODES

        codes_df = pl.DataFrame({"symbol": codes})
        dates_df = pl.DataFrame({"trade_date": dates_str})

        return codes_df.join(dates_df, how="cross").select(["symbol", "trade_date"])
