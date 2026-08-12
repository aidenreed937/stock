"""理杏仁 (Lixinger) 门面 (Facade) 数据抓取器实现模块。"""

from datetime import date

import polars as pl

from stock.data.fetcher.base import BaseDataFetcher
from stock.data.fetcher.lixinger.client import LixingerClient
from stock.data.fetcher.lixinger.stock_fetcher import LixingerStockFetcher
from stock.models.market import DailyBar


class LixingerDataFetcher(BaseDataFetcher):
    """理杏仁统一门面数据抓取器，实现 BaseDataFetcher 抽象接口。"""

    def __init__(
        self, token: str | None = None, url: str | None = None
    ) -> None:
        """初始化 LixingerDataFetcher 门面。

        Args:
            token: 理杏仁 API Token。若为 None，自动从配置文件读取。
            url: 理杏仁 API 服务器地址。若为 None，自动从配置文件读取。
        """
        self.client = LixingerClient(token=token, url=url)
        self.stock_fetcher = LixingerStockFetcher(client=self.client)

    def fetch_daily_bars(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[DailyBar]:
        """抓取日 K 线或估值数据并转换为 DailyBar 模型列表。"""
        return self.stock_fetcher.fetch_daily_bars(symbol, start_date, end_date)

    def fetch_daily_bars_df(
        self, symbol: str, start_date: date, end_date: date, endpoint: str = "cn/company/fundamental/non_financial"
    ) -> pl.DataFrame:
        """抓取行情或估值基本面数据，并返回 Polars 数据帧。"""
        return self.stock_fetcher.fetch_daily_bars_df(
            symbol, start_date, end_date, endpoint=endpoint
        )

    def fetch_trade_cal(
        self, start_date: date, end_date: date
    ) -> list[date]:
        """获取有效开市交易日列表。"""
        return self.stock_fetcher.fetch_trade_cal(start_date, end_date)
