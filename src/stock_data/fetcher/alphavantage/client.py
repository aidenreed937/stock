"""Alpha Vantage HTTP client with shared rate limiting."""

from __future__ import annotations

import logging
from typing import Any

from curl_cffi import requests

from stock_core.config.loader import load_data_config
from stock_core.config.settings import settings
from stock_data.fetcher.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class AlphaVantageError(RuntimeError):
    """Raised when Alpha Vantage returns an API or configuration error."""


class AlphaVantageClient:
    """Small client for Alpha Vantage query endpoints."""

    DEFAULT_BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        proxy: str | None = None,
        rate_limit_per_min: int | None = None,
        session: Any | None = None,
    ) -> None:
        data_cfg = load_data_config()
        self.api_key = settings.alpha_vantage_api_key if api_key is None else api_key
        self.base_url = base_url or settings.alpha_vantage_url or self.DEFAULT_BASE_URL
        self.proxy = settings.alpha_vantage_proxy if proxy is None else proxy
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
        self.rate_limiter.acquire()
        response = self.session.get(self.base_url, params=request_params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise AlphaVantageError("Alpha Vantage 返回格式不是 JSON object")

        for error_key in ("Error Message", "Information", "Note"):
            message = payload.get(error_key)
            if message:
                raise AlphaVantageError(f"Alpha Vantage [{error_key}]: {message}")
        return payload

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
