import logging
from datetime import date, timedelta
from typing import Any

import polars as pl

from stock.data.fetcher.base import BaseDataFetcher
from stock.data.fetcher.yfinance.client import YFinanceClient
from stock.data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY
from stock.models.market import DailyBar

logger = logging.getLogger(__name__)


class YFinanceDataFetcher(BaseDataFetcher):
    """Yahoo Finance 规范化行情抓取实现。"""

    def __init__(self, client: YFinanceClient) -> None:
        """初始化 YFinanceDataFetcher。

        Args:
            client: YFinanceClient 实例。
        """
        self.client = client

    def fetch_daily_bars(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[DailyBar]:
        """抓取指定标的代码的 K 线数据，转化为标准 DailyBar 模型。"""
        # yfinance 结束日期是 exclusive，加1天以包含该日期
        end_date_ex = end_date + timedelta(days=1)

        logger.info(f"YFinance 抓取 {symbol} 行情 (区间: {start_date} ~ {end_date})")

        try:
            df = self.client.query_history(
                symbol=symbol,
                start_date_str=start_date.isoformat(),
                end_date_str=end_date_ex.isoformat(),
            )

            if df.empty:
                logger.warning(f"YFinance 返回空数据: {symbol}")
                return []

            bars: list[DailyBar] = []
            for dt, row_series in df.iterrows():
                row: Any = row_series
                trade_date = dt.date() if hasattr(dt, "date") else dt
                volume = float(row["Volume"])
                close_price = float(row["Close"])
                amount = round(volume * close_price, 2)

                bars.append(
                    DailyBar(
                        symbol=symbol,
                        trade_date=trade_date,
                        open=round(float(row["Open"]), 4),
                        high=round(float(row["High"]), 4),
                        low=round(float(row["Low"]), 4),
                        close=round(close_price, 4),
                        volume=volume,
                        amount=amount,
                    )
                )
            logger.info(f"YFinance 成功抓取 {symbol} 共 {len(bars)} 条记录")
            return bars

        except Exception as e:
            logger.error(f"YFinance 抓取 {symbol} 失败: {e}", exc_info=True)
            return []

    def fetch_daily_bars_df(
        self, symbol: str, start_date: date, end_date: date, endpoint: str = "history"
    ) -> pl.DataFrame:
        """抓取指定标的行情数据，返回 Polars DataFrame。"""
        meta = YFINANCE_API_REGISTRY.get(endpoint)
        if not meta:
            logger.warning(f"未在注册表中找到 YFinance endpoint: {endpoint}")

        bars = self.fetch_daily_bars(symbol, start_date, end_date)
        if not bars:
            return pl.DataFrame()

        data_dicts = [bar.model_dump() for bar in bars]
        return pl.DataFrame(data_dicts)
