"""全市场日频聚合特征构建器 (MarketDailyBuilder)。

负责从底层 stock_daily_bar, margin, daily_basic, moneyflow, limit_list_d, opt_daily
等 Curated 数据集中按需投影字段，通过纯向量化计算生成全市场日频宽表并物化。
严格保证峰值内存 < 300 MB（计算完个股指标后立即聚合为日频并释放明细）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from stock.analytics.features.builders.market_daily_ops import (
    build_breadth_and_turnover,
    build_limit_features,
    build_margin_features,
    build_moneyflow_features,
    build_option_features,
    build_turnover_rate_features,
)
from stock.analytics.features.store import FeatureStore
from stock.data.catalog import DataCatalog
from stock.utils.logger import logger

if TYPE_CHECKING:
    from datetime import date


class MarketDailyBuilder:
    """全市场日频宽表构建器。"""

    def __init__(
        self,
        catalog: DataCatalog | None = None,
        store: FeatureStore | None = None,
        storage_dir: Path | str | None = None,
    ) -> None:
        """初始化 MarketDailyBuilder。"""
        self.catalog = catalog or DataCatalog(data_source="tushare", storage_dir=storage_dir)
        mart_path = Path(storage_dir) / "mart" if storage_dir else None
        self.store = store or FeatureStore(mart_dir=mart_path)

    def _join_margin_and_flow(self, result: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
        margin_df = build_margin_features(self.catalog, start, end)
        if not margin_df.is_empty():
            result = result.join(margin_df, on="trade_date", how="left")
            if "total_turnover" in result.columns and "margin_buy_amount" in result.columns:
                result = result.with_columns(
                    pl.when(pl.col("total_turnover") > 0)
                    .then(pl.col("margin_buy_amount") / pl.col("total_turnover"))
                    .otherwise(None)
                    .alias("margin_buy_ratio")
                )

        flow_df = build_moneyflow_features(self.catalog, start, end)
        if not flow_df.is_empty():
            result = result.join(flow_df, on="trade_date", how="left")
            if "total_turnover" in result.columns and "main_net_inflow" in result.columns:
                result = result.with_columns(
                    pl.when(pl.col("total_turnover") > 0)
                    .then(pl.col("main_net_inflow") / pl.col("total_turnover"))
                    .otherwise(None)
                    .alias("main_net_inflow_ratio")
                )
        return result

    def _join_auxiliary_features(
        self, result: pl.DataFrame, start: date, end: date
    ) -> pl.DataFrame:
        turnover_df = build_turnover_rate_features(self.catalog, start, end)
        if not turnover_df.is_empty():
            result = result.join(turnover_df, on="trade_date", how="left")

        limit_df = build_limit_features(self.catalog, start, end)
        if not limit_df.is_empty():
            result = result.join(limit_df, on="trade_date", how="left")

        if "margin_balance" in result.columns and "market_circ_mv" in result.columns:
            result = result.with_columns(
                pl.when(pl.col("market_circ_mv") > 0)
                .then(pl.col("margin_balance") / pl.col("market_circ_mv"))
                .otherwise(None)
                .alias("margin_penetration")
            )

        option_df = build_option_features(self.catalog, start, end)
        if not option_df.is_empty():
            result = result.join(option_df, on="trade_date", how="left")
        return result

    def build(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        save: bool = True,
        overwrite: bool = False,
    ) -> pl.DataFrame:
        """构建指定时间范围内的全市场日频宽表。"""
        logger.info(f"开始构建全市场日频特征宽表: start_date={start_date}, end_date={end_date}")

        breadth_df = build_breadth_and_turnover(self.catalog, start_date, end_date)
        if breadth_df.is_empty():
            logger.warning("未能从 stock_daily_bar 计算出任何行情/宽度特征")
            return pl.DataFrame()

        trade_dates = breadth_df["trade_date"].sort().to_list()
        actual_start = trade_dates[0]
        actual_end = trade_dates[-1]

        result = self._join_margin_and_flow(breadth_df, actual_start, actual_end)
        result = self._join_auxiliary_features(result, actual_start, actual_end)
        result = result.sort("trade_date")

        if save:
            self.store.save_market_daily(result, overwrite=overwrite)

        return result
