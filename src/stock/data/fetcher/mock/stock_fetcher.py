import random
from datetime import date, timedelta
from typing import Any

import polars as pl

from stock.data.fetcher.base import BaseDataFetcher
from stock.models.market import DailyBar


class MockDataFetcher(BaseDataFetcher):
    """模拟/测试数据源抓取器实现"""

    def fetch_daily_bars(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[DailyBar]:
        bars: list[DailyBar] = []
        current = start_date
        base_price = 100.0

        random.seed(42)  # 固定种子生成可复现数据

        while current <= end_date:
            # 跳过周末
            if current.weekday() < 5:
                change = random.uniform(-0.03, 0.03)
                open_price = round(base_price * (1 + random.uniform(-0.01, 0.01)), 2)
                close_price = round(base_price * (1 + change), 2)
                high_price = round(max(open_price, close_price) * 1.01, 2)
                low_price = round(min(open_price, close_price) * 0.99, 2)
                volume = float(random.randint(10000, 500000))
                amount = round(volume * close_price, 2)

                bars.append(
                    DailyBar(
                        symbol=symbol,
                        trade_date=current,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=volume,
                        amount=amount,
                    )
                )
                base_price = close_price
            current += timedelta(days=1)

        return bars

    def fetch_daily_bars_df(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        endpoint: str = "daily",
        **kwargs: Any,
    ) -> pl.DataFrame:
        bars = self.fetch_daily_bars(symbol, start_date, end_date)
        if not bars:
            return pl.DataFrame()

        data_dicts = [bar.model_dump() for bar in bars]
        return pl.DataFrame(data_dicts)

    def fetch_trade_cal(
        self, start_date: date, end_date: date
    ) -> list[date]:
        """模拟交易日历：过滤周六与周日。"""
        curr = start_date
        open_dates: list[date] = []
        while curr <= end_date:
            if curr.weekday() < 5:
                open_dates.append(curr)
            curr += timedelta(days=1)
        return open_dates
