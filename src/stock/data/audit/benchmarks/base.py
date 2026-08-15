"""领域事实基准提供者抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, timedelta

import polars as pl

from stock.utils.logger import logger


def get_trading_calendar(start_date: date, end_date: date) -> list[date]:
    """获取指定时间段内的开市交易日列表（优先尝试从 TuShare 获取，失败时按工作日自动降级）。"""
    try:
        from stock.data.fetcher.tushare.facade import TuShareDataFetcher

        fetcher = TuShareDataFetcher()
        cal = fetcher.fetch_trade_cal(start_date, end_date)
        if isinstance(cal, list) and cal:
            return [d for d in cal if isinstance(d, date)]
    except Exception as e:
        logger.debug(f"无法获取数据源交易日历: {e}，使用工作日降级策略")

    cur = start_date
    dates: list[date] = []
    while cur <= end_date:
        if cur.weekday() < 5:
            dates.append(cur)
        cur += timedelta(days=1)
    return dates


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
