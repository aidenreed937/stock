"""个股微观日频事实基准提供者 (全 A 股在市与停牌三方交叉基准)。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock.data.audit.benchmarks.base import BenchmarkProvider, get_trading_calendar

if TYPE_CHECKING:
    from stock.data.catalog import DataCatalog


class EquityDailyBenchmarkProvider(BenchmarkProvider):
    """全 A 股日频在市与停牌事实基准。

    预期集合公式: Expected(t) = TradingCalendar(t) × InMarketStocks(t)
    停牌集合公式: Suspended(t) = SuspendCalendar(t)
    """

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        if catalog is None:
            from stock.data.catalog import DataCatalog

            self.catalog = DataCatalog(data_source="tushare")
        else:
            self.catalog = catalog

    def get_expected_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        """根据交易日历与 stock_basic 上市/退市区间计算理论在市股票主键全集。"""
        # 1. 获取有效交易日历
        trading_dates = get_trading_calendar(start_date=start_date, end_date=end_date)
        if not trading_dates:
            return pl.DataFrame(
                {
                    "symbol": pl.Series([], dtype=pl.Utf8),
                    "trade_date": pl.Series([], dtype=pl.Utf8),
                }
            )

        # 2. 获取股票基础信息表
        df_basic = self.catalog.load_dataset("stock_basic")
        if df_basic.is_empty():
            return pl.DataFrame(
                {
                    "symbol": pl.Series([], dtype=pl.Utf8),
                    "trade_date": pl.Series([], dtype=pl.Utf8),
                }
            )

        # 统一清洗 basic 字段
        basic_clean = df_basic.select(
            [pl.col("symbol").cast(pl.Utf8), pl.col("list_date").cast(pl.Utf8)]
        ).drop_nulls()

        # 3. 构造交易日 DataFrame 并执行笛卡尔积 / 区间过滤
        dates_str = [d.strftime("%Y%m%d") for d in trading_dates]
        dates_df = pl.DataFrame({"trade_date": dates_str})

        expected = (
            basic_clean.join(dates_df, how="cross")
            .filter(pl.col("trade_date") >= pl.col("list_date"))
            .select(["symbol", "trade_date"])
            .unique()
        )
        return expected

    def get_suspended_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        """获取指定时间范围内的官方证实停牌集合。"""
        df_sus = self.catalog.load_dataset(
            "suspend_d", start_date=start_date, end_date=end_date
        )
        if df_sus.is_empty():
            return pl.DataFrame(
                {
                    "symbol": pl.Series([], dtype=pl.Utf8),
                    "trade_date": pl.Series([], dtype=pl.Utf8),
                }
            )

        sym_col = "symbol" if "symbol" in df_sus.columns else "ts_code"
        date_col = "trade_date" if "trade_date" in df_sus.columns else "suspend_date"
        if sym_col not in df_sus.columns or date_col not in df_sus.columns:
            return pl.DataFrame(
                {
                    "symbol": pl.Series([], dtype=pl.Utf8),
                    "trade_date": pl.Series([], dtype=pl.Utf8),
                }
            )

        return (
            df_sus.select(
                [
                    pl.col(sym_col).cast(pl.Utf8).alias("symbol"),
                    pl.col(date_col).cast(pl.Utf8).alias("trade_date"),
                ]
            )
            .drop_nulls()
            .unique()
        )
