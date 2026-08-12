import pandas as pd
import yfinance as yf


class YFinanceClient:
    """Yahoo Finance 客户端包装器。"""

    def __init__(self, proxy: str | None = None) -> None:
        """初始化 YFinance 客户端。

        Args:
            proxy: HTTP/HTTPS 代理服务器地址。
        """
        self.proxy = proxy

    def query_history(
        self, symbol: str, start_date_str: str, end_date_str: str
    ) -> pd.DataFrame:
        """调用 yfinance 接口拉取历史行情。

        Args:
            symbol: 标的代码。
            start_date_str: 开始日期字符串 (YYYY-MM-DD)。
            end_date_str: 结束日期字符串 (YYYY-MM-DD)。
        """
        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start_date_str,
            end=end_date_str,
            interval="1d",
            proxy=self.proxy,
        )
        return df
