"""全市场/宏观与截面数据分析模块。"""

from datetime import date

import polars as pl

from stock.data.storage.duckdb_store import DuckDBMarketStore


class MarketBreadthAnalyzer:
    """全市场广度分析器，用于计算大势指标（如站上均线的股票比例）。"""

    def __init__(self, store: DuckDBMarketStore) -> None:
        """初始化分析器。

        Args:
            store: 行情数据存储引擎。
        """
        self.store = store

    def calculate_breadth(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        window: int = 20,
    ) -> pl.DataFrame:
        """计算指定时间段内的市场广度 (站上 N 日均线的股票比例)。

        Args:
            start_date: 开始日期
            end_date: 结束日期
            window: 均线周期 (默认 20 日)

        Returns:
            pl.DataFrame: 包含 trade_date, total_stocks, stocks_above_ma, breadth_ratio 的结果表
        """
        # 1. 抓取全市场面板数据
        df = self.store.query_history(
            endpoint="stock_daily_bar", start_date=start_date, end_date=end_date
        )
        if df.is_empty():
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Date,
                    "total_stocks": pl.Int64,
                    "stocks_above_ma": pl.Int64,
                    "breadth_ratio": pl.Float64,
                }
            )

        # 2. 按标的分组计算 rolling mean，并判断是否站上均线
        df_analyzed = df.with_columns(
            pl.col("close").rolling_mean(window_size=window).over("symbol").alias(f"ma_{window}")
        ).with_columns((pl.col("close") > pl.col(f"ma_{window}")).alias("is_above"))

        # 3. 按日期分组统计广度
        return (
            df_analyzed.group_by("trade_date")
            .agg(
                [
                    pl.count("symbol").alias("total_stocks"),
                    pl.col("is_above").sum().cast(pl.Int64).alias("stocks_above_ma"),
                    (pl.col("is_above").sum() / pl.count("symbol")).alias("breadth_ratio"),
                ]
            )
            .sort("trade_date", descending=False)
        )
