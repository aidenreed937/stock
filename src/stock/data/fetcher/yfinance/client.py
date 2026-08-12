import threading
import time

from typing import Any

import pandas as pd
import yfinance as yf

from stock.config.loader import load_data_config
from stock.config.settings import settings
from stock.utils.logger import logger


class RateLimiter:
    """基于滑动时间窗口的线程安全速率限制器。"""

    def __init__(
        self, max_requests: int = 60, time_window_seconds: float = 60.0
    ) -> None:
        """初始化速率限制器。

        Args:
            max_requests: 窗口内最大请求次数。
            time_window_seconds: 时间窗口长度（单位：秒）。
        """
        self.max_requests = max_requests
        self.time_window = time_window_seconds
        self._requests: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """申请一次请求配额。若超过限制，则阻塞休眠直到解禁。"""
        if self.max_requests <= 0:
            return

        with self._lock:
            now = time.monotonic()
            self._requests = [t for t in self._requests if now - t < self.time_window]

            if len(self._requests) >= self.max_requests:
                sleep_time = self.time_window - (now - self._requests[0])
                if sleep_time > 0:
                    logger.warning(
                        f"触发 Yahoo Finance 频次限制 ({self.max_requests}次/分)，自动休眠 {sleep_time:.2f} 秒..."
                    )
                    time.sleep(sleep_time)
                now = time.monotonic()
                self._requests = [t for t in self._requests if now - t < self.time_window]

            self._requests.append(now)


class YFinanceClient:
    """Yahoo Finance 客户端包装器。

    支持滑动窗口限频（防 429 反爬封禁）与代理配置。
    """

    def __init__(
        self,
        proxy: str | None = None,
        rate_limit_per_min: int | None = None,
    ) -> None:
        """初始化 YFinance 客户端。

        Args:
            proxy: HTTP/HTTPS 代理服务器地址。若为 None，使用 settings.yfinance_proxy。
            rate_limit_per_min: 每分钟最大请求次数限制。若为 None，使用 settings.yfinance_rate_limit_per_min。
        """
        data_cfg = load_data_config()
        self.proxy = proxy if proxy is not None else settings.yfinance_proxy
        rate_limit = (
            rate_limit_per_min
            if rate_limit_per_min is not None
            else data_cfg.rate_limits.yfinance_per_min
        )
        self.rate_limiter = RateLimiter(max_requests=rate_limit)

    def _get_session(self) -> Any:
        """创建具备 Chrome TLS 指纹伪装与代理支持的 Session。"""
        try:
            from curl_cffi import requests as curl_requests

            c_session: Any = curl_requests.Session(impersonate="chrome")
            if self.proxy:
                c_session.proxies = {"http": self.proxy, "https": self.proxy}
            return c_session
        except Exception as e:
            logger.debug(f"未能使用 curl_cffi 伪装指纹: {e}")

        import requests

        r_session = requests.Session()
        if self.proxy:
            r_session.proxies = {"http": self.proxy, "https": self.proxy}
        return r_session

    def query_history(
        self, symbol: str, start_date_str: str, end_date_str: str
    ) -> pd.DataFrame:
        """调用 yfinance 接口拉取历史行情。

        Args:
            symbol: 标的代码。
            start_date_str: 开始日期字符串 (YYYY-MM-DD)。
            end_date_str: 结束日期字符串 (YYYY-MM-DD)。
        """
        self.rate_limiter.acquire()
        session = self._get_session()

        try:
            ticker = yf.Ticker(symbol, session=session)
            df = ticker.history(start=start_date_str, end=end_date_str, interval="1d")
            if not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Yahoo Finance Session 抓取异常 ({e})，尝试无 Session 直连...")

        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start_date_str,
            end=end_date_str,
            interval="1d",
        )
        return df
