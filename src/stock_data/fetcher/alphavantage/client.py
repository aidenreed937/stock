"""Alpha Vantage HTTP client with shared rate limiting."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from curl_cffi import requests

from stock_core.config.loader import load_data_config
from stock_data.core.settings import data_settings
from stock_data.fetcher.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class AlphaVantageError(RuntimeError):
    """Raised when Alpha Vantage returns an API or configuration error."""


class AlphaVantageClient:
    """Alpha Vantage 官方 HTTP API 客户端。"""

    DEFAULT_BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        proxy: str | None = None,
        rate_limit_per_min: int | None = None,
        session: Any | None = None,
        max_retries: int = 2,
        timeout: float = 30.0,
        backoff_factor: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        data_cfg = load_data_config()
        self.api_key = data_settings.alpha_vantage_api_key if api_key is None else api_key
        self.base_url = base_url or data_settings.alpha_vantage_url or self.DEFAULT_BASE_URL
        self.proxy = data_settings.alpha_vantage_proxy if proxy is None else proxy
        self.max_retries = max(0, int(max_retries))
        self.timeout = timeout
        self.backoff_factor = max(0.0, float(backoff_factor))
        self.sleep_fn = sleep_fn
        self.session: Any = session or requests.Session(impersonate="chrome")
        self.session.headers.update({"User-Agent": "stock-finance/alpha-vantage-client"})
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

        configured_rate = data_cfg.rate_limits.alpha_vantage_per_min
        self.rate_limiter = RateLimiter(max_requests=rate_limit_per_min or configured_rate)

    def _request(self, params: dict[str, str]) -> dict[str, Any]:
        if not self.api_key:
            raise AlphaVantageError("缺少 ALPHA_VANTAGE_API_KEY；请先配置 Alpha Vantage API key")

        request_params = {**params, "apikey": self.api_key}
        for attempt in range(self.max_retries + 1):
            self.rate_limiter.acquire()
            try:
                response = self.session.get(
                    self.base_url, params=request_params, timeout=self.timeout
                )
            except Exception as exc:
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt, None, exc)
                    continue
                raise AlphaVantageError(
                    f"Alpha Vantage 网络请求失败，重试 {self.max_retries} 次后仍失败: {exc}"
                ) from exc

            status = getattr(response, "status_code", None)
            if isinstance(status, int) and (status == 429 or status >= 500):
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt, response, status)
                    continue
                raise AlphaVantageError(
                    f"Alpha Vantage HTTP {status}，重试 {self.max_retries} 次后仍失败"
                )
            try:
                response.raise_for_status()
            except Exception as exc:
                raise AlphaVantageError(f"Alpha Vantage HTTP 请求失败: {exc}") from exc

            try:
                payload = response.json()
            except Exception as exc:
                raise AlphaVantageError(f"Alpha Vantage 返回 JSON 解析失败: {exc}") from exc
            if not isinstance(payload, dict):
                raise AlphaVantageError("Alpha Vantage 返回格式不是 JSON object")

            error_message = payload.get("Error Message")
            if error_message:
                raise AlphaVantageError(f"Alpha Vantage [Error Message]: {error_message}")
            for error_key in ("Information", "Note"):
                message = payload.get(error_key)
                if message:
                    if attempt < self.max_retries:
                        self._sleep_before_retry(attempt, response, message)
                        break
                    raise AlphaVantageError(f"Alpha Vantage [{error_key}]: {message}")
            else:
                return payload

        raise AlphaVantageError("Alpha Vantage 请求失败")

    def _sleep_before_retry(self, attempt: int, response: Any, detail: Any) -> None:
        retry_after = None
        if response is not None:
            headers = getattr(response, "headers", {}) or {}
            raw_retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
            if raw_retry_after is not None:
                try:
                    retry_after = max(0.0, float(raw_retry_after))
                except (TypeError, ValueError):
                    retry_after = None
        delay = retry_after if retry_after is not None else self.backoff_factor * (2**attempt)
        logger.warning("Alpha Vantage 请求暂时失败 (%s)，将在 %.2f 秒后重试", detail, delay)
        self.sleep_fn(delay)

    def fetch_fx_daily_raw(
        self,
        from_symbol: str,
        to_symbol: str,
        outputsize: str = "full",
    ) -> dict[str, dict[str, Any]]:
        """Fetch raw daily FX OHLC data for a currency pair."""
        payload = self._request(
            {
                "function": "FX_DAILY",
                "from_symbol": from_symbol,
                "to_symbol": to_symbol,
                "outputsize": outputsize,
            }
        )
        series = payload.get("Time Series FX (Daily)")
        if not isinstance(series, dict):
            raise AlphaVantageError(
                "Alpha Vantage FX_DAILY response has no 'Time Series FX (Daily)'"
            )
        return series

    def get(self, endpoint: str, **kwargs: Any) -> dict[str, dict[str, Any]]:
        """Compatibility entry point for registered Alpha Vantage endpoints."""
        if endpoint.upper() != "FX_DAILY":
            raise AlphaVantageError(f"Unsupported Alpha Vantage endpoint: {endpoint}")
        return self.fetch_fx_daily_raw(
            from_symbol=str(kwargs["from_symbol"]),
            to_symbol=str(kwargs["to_symbol"]),
            outputsize=str(kwargs.get("outputsize", "full")),
        )
