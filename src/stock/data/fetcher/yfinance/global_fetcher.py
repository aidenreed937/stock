import logging
from datetime import date, timedelta

import polars as pl
import yfinance as yf

from stock.data.fetcher.base import BaseDataFetcher
from stock.models.market import DailyBar

logger = logging.getLogger(__name__)


class YFinanceDataFetcher(BaseDataFetcher):
    """Yahoo Finance 全球/海外多资产行情抓取实现。"""

    def __init__(self, proxy: str | None = None) -> None:
        """初始化 YFinance 抓取器。

        Args:
            proxy: HTTP/HTTPS 代理服务器地址（格式如 "http://127.0.0.1:7890"），
                  中国大陆直连 Yahoo API 易超时，建议配置代理。
        """
        self.proxy = proxy

    def fetch_daily_bars(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[DailyBar]:
        """从 Yahoo Finance 抓取海外资产的日线 K 线行情。

        Args:
            symbol: 标的代码，如 "^GSPC" (标普500), "AAPL" (苹果), "GC=F" (黄金期货)
            start_date: 开始日期 (含)
            end_date: 结束日期 (含)
        """
        # Yahoo Finance 的 end 日期是 exclusive (不含)，因此加 1 天以包含 end_date
        end_date_ex = end_date + timedelta(days=1)

        logger.info(
            f"开始从 Yahoo Finance 抓取 {symbol} 行情 (区间: {start_date} ~ {end_date}, "
            f"代理: {self.proxy or '无'})"
        )

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(
                start=start_date.isoformat(),
                end=end_date_ex.isoformat(),
                interval="1d",
                proxy=self.proxy,
            )

            if df.empty:
                logger.warning(f"Yahoo Finance 返回数据为空: {symbol}")
                return []

            bars: list[DailyBar] = []
            for dt, row in df.iterrows():
                # 处理日期类型
                trade_date = dt.date() if hasattr(dt, "date") else dt

                # volume 并入 amount 估算
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

            logger.info(f"成功获取 {symbol} 共 {len(bars)} 条 K 线记录")
            return bars

        except Exception as e:
            logger.error(f"Yahoo Finance 抓取 {symbol} 失败: {e}", exc_info=True)
            return []

    def fetch_daily_bars_df(
        self, symbol: str, start_date: date, end_date: date, endpoint: str = "daily"
    ) -> pl.DataFrame:
        """从 Yahoo Finance 抓取行情并返回为标准 Polars DataFrame。"""
        bars = self.fetch_daily_bars(symbol, start_date, end_date)
        if not bars:
            return pl.DataFrame()

        data_dicts = [bar.model_dump() for bar in bars]
        return pl.DataFrame(data_dicts)
