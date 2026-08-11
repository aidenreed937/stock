import threading
import time
from typing import Any

import pandas as pd
import tushare as ts

from stock.config.settings import settings
from stock.exceptions import DataFetchError
from stock.utils.logger import logger


class RateLimiter:
    """基于滑动时间窗口的线程安全速率限制器。"""

    def __init__(
        self, max_requests: int = 200, time_window_seconds: float = 60.0
    ) -> None:
        """初始化速率限制器。

        Args:
            max_requests: 窗口内最大请求次数。
            time_window_seconds: 时间窗口长度（单位：秒）。
        """
        self.max_requests = max_requests
        self.time_window = time_window_seconds
        self.requests: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """申请一次请求配额。若超过限制，则阻塞休眠直到解禁。"""
        if self.max_requests <= 0:
            return

        with self._lock:
            now = time.monotonic()
            # 清除窗口期之外的旧请求记录
            self.requests = [t for t in self.requests if now - t < self.time_window]

            if len(self.requests) >= self.max_requests:
                sleep_time = self.time_window - (now - self.requests[0])
                if sleep_time > 0:
                    logger.warning(
                        f"触发 TuShare 频次限制 ({self.max_requests}次/分)，自动休眠 {sleep_time:.2f} 秒..."
                    )
                    time.sleep(sleep_time)
                now = time.monotonic()
                self.requests = [t for t in self.requests if now - t < self.time_window]

            self.requests.append(now)


class TuShareClient:
    """TuShare 官方 Pro API 底层客户端封装。

    提供 Token 鉴权管理、线程安全滑动窗口限频、多 Worker 并发支持与 DataFetchError 抛出。
    """

    def __init__(
        self,
        token: str | None = None,
        url: str | None = None,
        rate_limit_per_min: int | None = None,
        max_workers: int | None = None,
    ) -> None:
        """初始化 TuShare 客户端。

        Args:
            token: TuShare API Token。若为 None，则从 settings.tushare_token 中读取。
            url: TuShare API 服务器地址。若为 None，则从 settings.tushare_url 中读取。
            rate_limit_per_min: 每分钟最大请求次数限制。若为 None，则从 settings.tushare_rate_limit_per_min 读取。
            max_workers: 并发采集 Worker 线程数。若为 None，则从 settings.tushare_max_workers 读取。
        """
        self.token = token or settings.tushare_token
        self.url = url or settings.tushare_url
        self.rate_limit_per_min = (
            rate_limit_per_min
            if rate_limit_per_min is not None
            else settings.tushare_rate_limit_per_min
        )
        self.max_workers = (
            max_workers
            if max_workers is not None
            else settings.tushare_max_workers
        )

        self.rate_limiter = RateLimiter(max_requests=self.rate_limit_per_min)
        self._pro_api: Any = None

    @property
    def pro(self) -> Any:
        """延迟初始化并返回 TuShare Pro API 实例。

        Raises:
            DataFetchError: 未配置 Token 时抛出。
        """
        if self._pro_api is None:
            if not self.token:
                raise DataFetchError(
                    "未配置 TuShare API Token！请在 .env 文件中设置 TUSHARE_TOKEN=your_token"
                )
            ts.set_token(self.token)
            if self.url:
                self._pro_api = ts.pro_api(server=self.url)
            else:
                self._pro_api = ts.pro_api()
            logger.debug(
                f"TuShare Pro API 初始化成功 [server: {self.url or 'default'}, "
                f"rate_limit: {self.rate_limit_per_min}/min, workers: {self.max_workers}]"
            )
        return self._pro_api

    def query(self, api_name: str, **kwargs: Any) -> pd.DataFrame:
        """调用指定 TuShare 接口并返回 Pandas DataFrame (自动做滑动窗口限频)。

        Args:
            api_name: TuShare API 接口名（如 daily, fina_indicator）。
            **kwargs: 传给 API 的查询参数。

        Returns:
            pd.DataFrame: 原始响应数据帧。

        Raises:
            DataFetchError: 接口请求异常或 Token 无效时抛出。
        """
        self.rate_limiter.acquire()
        try:
            logger.debug(f"TuShare 请求: api_name={api_name}, kwargs={kwargs}")
            df: pd.DataFrame = self.pro.query(api_name, **kwargs)
            if df is None:
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.error(f"TuShare API 请求失败 [{api_name}]: {e}")
            raise DataFetchError(f"TuShare 接口 [{api_name}] 请求失败: {e}") from e
