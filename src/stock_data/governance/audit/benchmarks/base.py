"""领域事实基准提供者抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import polars as pl

from stock_core.utils.logger import logger


def get_trading_calendar(start_date: date, end_date: date) -> list[date]:
    """获取指定时间段内的开市交易日列表，缺少日历时返回空列表。"""
    try:
        from stock_data.pipeline.scheduler import DataUpdateScheduler

        return list(DataUpdateScheduler.get_trading_days(start_date, end_date, "tushare"))
    except Exception as e:
        logger.warning(f"无法获取 TuShare 交易日历，拒绝按工作日推算: {e}")
        return []


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
