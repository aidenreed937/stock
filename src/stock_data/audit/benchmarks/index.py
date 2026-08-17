"""大盘指数日频事实基准提供者 (10 大核心宽基指数基准)。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock_data.audit.benchmarks.base import BenchmarkProvider, get_trading_calendar

if TYPE_CHECKING:
    from stock_data.catalog import DataCatalog


# 观察池国内 10 大核心宽基与大盘指数 (默认兜底)
CORE_INDEX_CODES: list[str] = [
    "000001.SH",  # 上证指数
    "399001.SZ",  # 深证成指
    "000300.SH",  # 沪深300
    "000905.SH",  # 中证500
    "000852.SH",  # 中证1000
    "000016.SH",  # 上证50
    "399006.SZ",  # 创业板指
    "000688.SH",  # 科创50
    "000985.CSI",  # 中证全指
    "399102.SZ",  # 创业板综
]


class IndexDailyBenchmarkProvider(BenchmarkProvider):
    """核心宽基指数日频事实基准提供者。

    预期集合公式: Expected(t) = TradingCalendar(t) × WatchlistIndices(t) (结合指数基准日)
    """

    def __init__(
        self,
        catalog: DataCatalog | None = None,
        indices: list[str] | None = None,
        base_dates: dict[str, str] | None = None,
    ) -> None:
        if catalog is None:
            from stock_data.catalog import DataCatalog

            self.catalog = DataCatalog(data_source="tushare")
        else:
            self.catalog = catalog

        self.base_dates: dict[str, str] = base_dates or {}
        if indices is not None:
            self.indices = indices
        else:
            try:
                from stock_core.config.loader import load_watchlist_config

                wl = load_watchlist_config()
                ts_wl = getattr(wl, "tushare", None)
                if ts_wl and ts_wl.indices:
                    self.indices = ts_wl.indices
                    if not self.base_dates and ts_wl.base_dates:
                        self.base_dates = ts_wl.base_dates
                else:
                    self.indices = CORE_INDEX_CODES
            except Exception:
                self.indices = CORE_INDEX_CODES

    def get_expected_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        """根据交易日历与核心指数列表（结合基准日）生成预期主键全集。"""
        trading_dates = get_trading_calendar(start_date=start_date, end_date=end_date)
        if not trading_dates or not self.indices:
            return pl.DataFrame(
                {
                    "symbol": pl.Series([], dtype=pl.Utf8),
                    "trade_date": pl.Series([], dtype=pl.Utf8),
                }
            )

        records: list[dict[str, str]] = []
        for d in trading_dates:
            d_str_compact = d.strftime("%Y%m%d")
            d_str_iso = d.strftime("%Y-%m-%d")
            for sym in self.indices:
                base_d = self.base_dates.get(sym) or self.base_dates.get(sym.split(".")[0])
                if base_d and d_str_iso < base_d:
                    continue
                records.append({"symbol": sym, "trade_date": d_str_compact})

        if not records:
            return pl.DataFrame(
                {
                    "symbol": pl.Series([], dtype=pl.Utf8),
                    "trade_date": pl.Series([], dtype=pl.Utf8),
                }
            )

        return pl.DataFrame(records).select(["symbol", "trade_date"]).unique()
