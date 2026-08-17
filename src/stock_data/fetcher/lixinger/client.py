"""理杏仁 (Lixinger) 官方开放平台 API 底层客户端封装模块。"""

import threading
import time
from datetime import date
from typing import Any

import pandas as pd
import requests

from stock_core.config.loader import load_data_config
from stock_core.config.settings import settings
from stock_core.exceptions import DataFetchError
from stock_core.utils.logger import logger
from stock_data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY
from stock_data.fetcher.rate_limiter import RateLimiter

MAX_STOCK_CODES = 100

_SHARED_LIMITERS: dict[tuple[str, int], RateLimiter] = {}
_SHARED_LIMITERS_LOCK = threading.Lock()


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
        """根据接口类型获取当前进程共享的 RateLimiter 实例。"""
        meta = LIXINGER_API_REGISTRY.get(api_path)
        limit = meta.rate_limit_per_min if meta else self.default_rate_limit
        limiter_key = (api_path, limit)
        with _SHARED_LIMITERS_LOCK:
            limiter = _SHARED_LIMITERS.get(limiter_key)
            if limiter is None:
                limiter = RateLimiter(max_requests=limit)
                _SHARED_LIMITERS[limiter_key] = limiter
            self._limiters[api_path] = limiter
            return limiter

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
            logger.warning("理杏仁 Token 未设置！返回空结果。")
            return pd.DataFrame()

        self._validate_date_range(api_path, kwargs)

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
                    logger.warning(f"理杏仁网络请求失败: {exc}，将在 {delay} 秒后重试...")
                    time.sleep(delay)
                    continue
                raise DataFetchError(
                    f"理杏仁网络请求失败，已重试 {self.max_retries} 次: {exc}"
                ) from exc

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

    def query_batch(
        self, api_path: str, stock_codes: list[str] | tuple[str, ...], **kwargs: Any
    ) -> pd.DataFrame:
        """按理杏仁接口约束批量查询并合并多个股票或指数代码。"""
        if "stockCodes" in kwargs:
            raise DataFetchError("query_batch 不应同时传入 stockCodes 参数")
        if not isinstance(stock_codes, list | tuple):
            raise DataFetchError("理杏仁批量查询 stock_codes 必须是数组")

        codes = [str(code).strip() for code in stock_codes]
        if not codes or any(not code for code in codes):
            raise DataFetchError("理杏仁批量查询 stock_codes 不能为空")

        # 理杏仁的历史区间请求带 startDate 时只能传一个代码；date 查询才可按 100 个代码批量。
        start_value = kwargs.get("startDate") or kwargs.get("start_date")
        if start_value and len(codes) > 1:
            code_groups = [[code] for code in codes]
        else:
            code_groups = [
                codes[index : index + MAX_STOCK_CODES]
                for index in range(0, len(codes), MAX_STOCK_CODES)
            ]

        frames: list[pd.DataFrame] = []
        for code_group in code_groups:
            frame = self.query(api_path, stockCodes=code_group, **kwargs)
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True, sort=False)

    @staticmethod
    def _validate_date_range(api_path: str, kwargs: dict[str, Any]) -> None:
        """在 HTTP 请求前执行理杏仁文档的最长十年时间窗约束。"""
        stock_codes = kwargs.get("stockCodes")
        if stock_codes is not None:
            if not isinstance(stock_codes, list | tuple):
                raise DataFetchError(f"理杏仁接口 [{api_path}] stockCodes 必须是数组")
            if not 1 <= len(stock_codes) <= MAX_STOCK_CODES:
                raise DataFetchError(
                    f"理杏仁接口 [{api_path}] stockCodes 数量必须在 1~{MAX_STOCK_CODES} 之间，"
                    f"实际 {len(stock_codes)}"
                )
        start_value = kwargs.get("startDate") or kwargs.get("start_date")
        end_value = kwargs.get("endDate") or kwargs.get("end_date")
        if start_value and stock_codes is not None and len(stock_codes) != 1:
            raise DataFetchError(
                f"理杏仁接口 [{api_path}] 带 startDate 的历史区间请求只能传入一个 stockCode，实际 {len(stock_codes)} 个"
            )
        if not start_value or not end_value:
            return
        try:
            start = date.fromisoformat(str(start_value)[:10])
            end = date.fromisoformat(str(end_value)[:10])
        except ValueError as exc:
            raise DataFetchError(
                f"理杏仁接口 [{api_path}] 日期参数必须为 YYYY-MM-DD: start={start_value}, end={end_value}"
            ) from exc
        if end < start:
            raise DataFetchError(f"理杏仁接口 [{api_path}] endDate 早于 startDate")
        if (end - start).days > 3650:
            raise DataFetchError(
                f"理杏仁接口 [{api_path}] 请求跨度超过文档限制 10 年: {start} ~ {end}"
            )
