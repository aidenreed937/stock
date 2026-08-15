"""大盘指数日频事实基准提供者 (10 大核心宽基指数基准)。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock.data.audit.benchmarks.base import BenchmarkProvider, get_trading_calendar

if TYPE_CHECKING:
    from stock.data.catalog import DataCatalog


# 观察池国内 10 大核心宽基与大盘指数
CORE_INDEX_CODES: list[str] = [
    "000001.SH",  # 上证指数
    "399001.SZ",  # 深证成指
    "000300.SH",  # 沪深300
    "000905.SH",  # 中证500
    "000852.SH",  # 中证1000
    "000016.SH",  # 上证50
    "399006.SZ",  # 创业板指
    "688981.SH",  # 科创50 (或 000688.SH)
    "000985.CSI",  # 中证全指
    "399102.SZ",  # 创业板综
]


class IndexDailyBenchmarkProvider(BenchmarkProvider):
    """核心宽基指数日频事实基准提供者。

    预期集合公式: Expected(t) = TradingCalendar(t) × WatchlistIndices(10)
    """

    def __init__(
        self,
        catalog: DataCatalog | None = None,
        indices: list[str] | None = None,
    ) -> None:
        self.indices = indices or CORE_INDEX_CODES
        if catalog is None:
            from stock.data.catalog import DataCatalog

            self.catalog = DataCatalog(data_source="tushare")
        else:
            self.catalog = catalog

    def get_expected_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        """根据交易日历与核心指数列表生成预期主键全集。"""
        trading_dates = get_trading_calendar(start_date=start_date, end_date=end_date)
        if not trading_dates:
            return pl.DataFrame(
                {
                    "symbol": pl.Series([], dtype=pl.Utf8),
                    "trade_date": pl.Series([], dtype=pl.Utf8),
                }
            )

        dates_str = [d.strftime("%Y%m%d") for d in trading_dates]
        codes_df = pl.DataFrame({"symbol": self.indices})
        dates_df = pl.DataFrame({"trade_date": dates_str})

        return codes_df.join(dates_df, how="cross").select(["symbol", "trade_date"])
