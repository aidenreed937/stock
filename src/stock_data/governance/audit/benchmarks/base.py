"""领域事实基准提供者抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import polars as pl

from stock_core.utils.logger import logger
from stock_data.pipeline.cleaner.date_utils import parse_mixed_date


def get_trading_calendar(start_date: date, end_date: date) -> list[date]:
    """获取指定时间段内的开市交易日列表，缺少日历时返回空列表。"""
    try:
        from stock_data.pipeline.scheduler import DataUpdateScheduler

        return list(DataUpdateScheduler.get_trading_days(start_date, end_date, "tushare"))
    except Exception as e:
        logger.warning(f"无法获取 TuShare 交易日历，拒绝按工作日推算: {e}")
        return []


def active_in_market(frame: pl.DataFrame, target_date: date) -> pl.DataFrame:
    """按统一规则保留 ``list_date <= t < delist_date`` 的标的。"""
    if "list_date" not in frame.columns:
        return frame.head(0)
    result = frame.with_columns(parse_mixed_date("list_date").alias("_list_date"))
    if "delist_date" in result.columns:
        result = result.with_columns(parse_mixed_date("delist_date").alias("_delist_date"))
        return result.filter(
            (pl.col("_list_date") <= pl.lit(target_date))
            & (pl.col("_delist_date").is_null() | (pl.col("_delist_date") > pl.lit(target_date)))
        ).drop(["_list_date", "_delist_date"])
    return result.filter(pl.col("_list_date") <= pl.lit(target_date)).drop("_list_date")


class BenchmarkProvider(ABC):
    """领域事实基准提供者 (SSOT Ground Truth Reference Provider)。"""

    @abstractmethod
    def get_expected_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        """返回指定时间段内理论上应该存在的预期主键集合。

        Returns:
            pl.DataFrame: 包含 ["symbol", "trade_date"] 列的 Polars DataFrame。
        """

    def get_suspended_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        """返回指定时间段内合法的免责/停牌主键集合 (用于容错剔除)。

        Returns:
            pl.DataFrame: 包含 ["symbol", "trade_date"] 列的 Polars DataFrame。
        """
        return pl.DataFrame(
            {"symbol": pl.Series([], dtype=pl.Utf8), "trade_date": pl.Series([], dtype=pl.Utf8)}
        )


class UnsupportedBenchmarkProvider(BenchmarkProvider):
    """占位基准，供未注册数据集安全返回 UNSUPPORTED。"""

    def get_expected_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        return pl.DataFrame(
            {"symbol": pl.Series([], dtype=pl.Utf8), "trade_date": pl.Series([], dtype=pl.Utf8)}
        )
