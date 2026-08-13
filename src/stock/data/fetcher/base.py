from abc import ABC, abstractmethod
from datetime import date

import polars as pl

from stock.models.market import DailyBar


class BaseDataFetcher(ABC):
    """行情数据抓取抽象基类"""

    @abstractmethod
    def fetch_daily_bars(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[DailyBar]:
        """抓取指定股票及时间段的 K 线数据，返回验证后的模型列表"""
        pass

    @abstractmethod
    def fetch_daily_bars_df(
        self, symbol: str, start_date: date, end_date: date, endpoint: str = "stock_daily_bar"
    ) -> pl.DataFrame:
        """抓取行情或基本面数据，转化为标准 Polars DataFrame。"""
        pass
