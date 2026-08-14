import logging
from datetime import date
from typing import Any

import polars as pl

from stock.data.fetcher.base import BaseDataFetcher
from stock.data.fetcher.fred.client import FredClient
from stock.data.fetcher.fred.registry import FRED_API_REGISTRY

logger = logging.getLogger(__name__)


class FredDataFetcher(BaseDataFetcher):
    """FRED 官方宏观经济数据 Fetcher 实现。"""

    def __init__(self, client: FredClient | None = None, proxy: str | None = None) -> None:
        """初始化 FRED 数据抓取器。"""
        self.client = client or FredClient(proxy=proxy)

    def fetch_daily_bars(self, symbol: str, start_date: date, end_date: date) -> list[Any]:
        """兼容 BaseDataFetcher 接口。将宏观数据点映射为标准序列。"""
        return []

    def fetch_daily_bars_df(
        self, symbol: str, start_date: date, end_date: date, endpoint: str = "history"
    ) -> pl.DataFrame:
        """实现 BaseDataFetcher 接口。抓取指定 FRED 宏观序列。"""
        if endpoint == "macro_indicators" or symbol == "macro_indicators":
            return self.fetch_macro_indicators_df(start_date, end_date)
        return self.fetch_series_df(symbol, start_date, end_date)

    def fetch_series_df(self, series_id: str, start_date: date, end_date: date) -> pl.DataFrame:
        """抓取指定 FRED 宏观序列 (如 FEDFUNDS, CPIAUCSL, UNRATE) 并过滤时间切片。"""
        raw_df = self.client.fetch_series_raw(series_id)
        if raw_df.empty:
            return pl.DataFrame()

        # 标准化 Polars DataFrame: symbol, trade_date, value, series_name
        meta = FRED_API_REGISTRY.get(series_id.upper())
        val_col = series_id.upper()
        if val_col not in raw_df.columns:
            return pl.DataFrame()

        pl_df = pl.from_pandas(raw_df)
        pl_df = pl_df.rename({"DATE": "date_str", val_col: "value"})
        pl_df = pl_df.with_columns(
            pl.col("date_str").str.to_date("%Y-%m-%d").alias("trade_date"),
            pl.lit(series_id.upper()).alias("symbol"),
            pl.lit(meta.description if meta else series_id).alias("description"),
            pl.lit(meta.units if meta else "index").alias("units"),
            pl.lit("fred").alias("data_source"),
        )

        # 过滤时间范围
        pl_df = pl_df.filter(
            (pl.col("trade_date") >= start_date) & (pl.col("trade_date") <= end_date)
        )
        return pl_df.with_columns(
            pl.col("value").alias("close"),
            pl.col("value").alias("open"),
            pl.col("value").alias("high"),
            pl.col("value").alias("low"),
            pl.lit(0.0).alias("volume"),
            pl.lit(0.0).alias("amount"),
        ).select(
            [
                "symbol",
                "trade_date",
                "value",
                "close",
                "open",
                "high",
                "low",
                "volume",
                "amount",
                "description",
                "units",
                "data_source",
            ]
        )

    def fetch_macro_indicators_df(
        self,
        start_date: date,
        end_date: date,
        series_ids: list[str] | None = None,
    ) -> pl.DataFrame:
        """一行代码批量同步抓取 FRED 核心宏观指标。"""
        default_series = ["FEDFUNDS", "CPIAUCSL", "UNRATE", "T10Y2Y", "WALCL"]
        targets = series_ids or default_series

        frames: list[pl.DataFrame] = []
        for sid in targets:
            df = self.fetch_series_df(sid, start_date, end_date)
            if not df.is_empty():
                frames.append(df)

        if not frames:
            return pl.DataFrame()

        return pl.concat(frames, how="diagonal_relaxed")
