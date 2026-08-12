"""理杏仁 (Lixinger) 官方开放平台 API 底层客户端封装模块。"""

import threading
import time
from typing import Any

import pandas as pd
import requests

from stock.config.loader import load_data_config
from stock.config.settings import settings
from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY
from stock.exceptions import DataFetchError
from stock.utils.logger import logger


class RateLimiter:
    """基于滑动时间窗口的线程安全速率限制器。"""

    def __init__(
        self, max_requests: int = 1000, time_window_seconds: float = 60.0
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
            # 清除窗口期之外的旧请求记录
            self._requests = [t for t in self._requests if now - t < self.time_window]

            if len(self._requests) >= self.max_requests:
                sleep_time = self.time_window - (now - self._requests[0])
                if sleep_time > 0:
                    logger.warning(
                        f"触发理杏仁 API 频次限制 ({self.max_requests}次/分)，自动休眠 {sleep_time:.2f} 秒..."
                    )
                    time.sleep(sleep_time)
                now = time.monotonic()
                self._requests = [t for t in self._requests if now - t < self.time_window]

            self._requests.append(now)


class LixingerClient:
    """理杏仁开放平台 HTTP API 底层客户端。

    提供 Token 鉴权注入、按接口粒度滑动窗口限频、HTTP POST 请求封装、状态码判定与指数退避重试机制。
    """

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        token: str | None = None,
        url: str | None = None,
        rate_limit_per_min: int | None = None,
        max_retries: int = 5,
        timeout: float = 15.0,
    ) -> None:
        """初始化理杏仁客户端。

        Args:
            token: 理杏仁 API Token。若为 None，从 settings.lixinger_token 读取。
            url: 理杏仁 API 域名。若为 None，从 settings.lixinger_url 读取。
            rate_limit_per_min: 每分钟最大请求次数。若为 None，从 settings 读取。
            max_retries: 429 或 5xx 错误的最大退避重试次数。
            timeout: HTTP 请求超时时间（秒）。
        """
        data_cfg = load_data_config()
        self.token = token if token is not None else settings.effective_lixinger_token
        self.url = (url if url is not None else settings.effective_lixinger_url).rstrip("/")
        self.default_rate_limit = (
            rate_limit_per_min
            if rate_limit_per_min is not None
            else data_cfg.rate_limits.lixinger_per_min
        )
        self._limiters: dict[str, RateLimiter] = {}
        self._limiter_lock = threading.Lock()
        self.max_retries = max_retries
        self.timeout = timeout
        self._session = requests.Session()

    def _get_rate_limiter(self, api_path: str) -> RateLimiter:
        """根据接口类型获取独立的 RateLimiter 实例。"""
        with self._limiter_lock:
            if api_path not in self._limiters:
                meta = LIXINGER_API_REGISTRY.get(api_path)
                limit = meta.rate_limit_per_min if meta else self.default_rate_limit
                self._limiters[api_path] = RateLimiter(max_requests=limit)
            return self._limiters[api_path]

    def query(self, api_path: str, **kwargs: Any) -> pd.DataFrame:
        """执行理杏仁 API POST 查询请求并转化为 pandas DataFrame。

        Args:
            api_path: 接口路径或名称（如 'cn/company/fundamental/non_financial' 或完整 URL）。
            **kwargs: 传给 API requestBody 的请求参数。

        Returns:
            pd.DataFrame: 解析后的结果数据框。

        Raises:
            DataFetchError: 当缺少 Token、请求校验失败、Token 无效或重试用尽时抛出。
        """
        if not self.token:
            logger.warning("理杏仁 Token 未设置！使用 Mock 或空结果返回。")
            return pd.DataFrame()

        full_url = api_path if api_path.startswith("http") else f"{self.url}/api/{api_path}"

        headers = {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip, deflate, br, zstd",
        }

        body_data = {"token": self.token, **kwargs}

        retry_delays = [1, 2, 4, 8, 16]

        limiter = self._get_rate_limiter(api_path)

        for attempt in range(self.max_retries + 1):
            limiter.acquire()
            logger.debug(f"理杏仁请求 [{attempt + 1}/{self.max_retries + 1}]: url={full_url}")

            try:
                response = self._session.post(
                    full_url, json=body_data, headers=headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.warning(
                        f"理杏仁网络请求失败: {exc}，将在 {delay} 秒后重试..."
                    )
                    time.sleep(delay)
                    continue
                raise DataFetchError(f"理杏仁网络请求失败，已重试 {self.max_retries} 次: {exc}") from exc

            status = response.status_code

            if status == 400:
                msg = f"理杏仁 API 参数验证失败 (400): {response.text}"
                logger.error(msg)
                raise DataFetchError(msg)
            if status == 401:
                msg = f"理杏仁 Token 验证失效 (401)，请检查 LIXINGER_TOKEN 配置: {response.text}"
                logger.error(msg)
                raise DataFetchError(msg)
            if status == 403:
                msg = f"理杏仁 API 权限不足或额度耗尽 (403): {response.text}"
                logger.error(msg)
                raise DataFetchError(msg)
            if status == 429:
                if attempt < self.max_retries:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.warning(f"理杏仁 API 触发限流 (429)，等待 {delay} 秒后重试...")
                    time.sleep(delay)
                    continue
                raise DataFetchError(f"理杏仁 API 限流重试次数超限 ({self.max_retries} 次)")

            if status >= 500:
                if attempt < self.max_retries:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.warning(f"理杏仁 API 服务器错误 ({status})，等待 {delay} 秒后重试...")
                    time.sleep(delay)
                    continue
                raise DataFetchError(f"理杏仁 API 服务器响应异常 ({status}): {response.text}")

            try:
                res_json = response.json()
            except ValueError as exc:
                raise DataFetchError(f"理杏仁 API 响应解析 JSON 失败: {response.text}") from exc

            # 理杏仁 API 协议返回格式判定
            if isinstance(res_json, dict):
                if "error" in res_json:
                    err_info = res_json.get("error")
                    code = res_json.get("code", 0)
                    raise DataFetchError(f"理杏仁 API 返回业务错误 [{code}]: {err_info}")

                data = res_json.get("data")
                if data is None and res_json.get("code") not in (1, 200, 0):
                    code = res_json.get("code")
                    msg_text = res_json.get("msg") or res_json.get("message", "")
                    raise DataFetchError(f"理杏仁 API 返回业务错误 [{code}]: {msg_text}")

                if isinstance(data, list):
                    return pd.DataFrame(data)
                if isinstance(data, dict):
                    return pd.DataFrame([data])
                return pd.DataFrame(res_json)
            if isinstance(res_json, list):
                return pd.DataFrame(res_json)

            return pd.DataFrame()

        return pd.DataFrame()
