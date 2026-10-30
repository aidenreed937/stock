"""Alpha Vantage HTTP client with shared rate limiting."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_core.config.loader import load_data_config
from stock_data.core.settings import data_settings
from stock_data.fetcher.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_USAGE_LOCKS_GUARD = threading.Lock()
_USAGE_LOCKS: dict[Path, threading.Lock] = {}


def _usage_lock(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _USAGE_LOCKS_GUARD:
        lock = _USAGE_LOCKS.get(resolved)
        if lock is None:
            lock = threading.Lock()
            _USAGE_LOCKS[resolved] = lock
        return lock


class AlphaVantageUsageStore:
    """按 Key 记录每日请求次数，不在本地落盘原始 Key。"""

    def __init__(self, path: Path, daily_limit: int) -> None:
        self.path = path
        self.daily_limit = max(1, int(daily_limit))
        self._lock = _usage_lock(path)

    @staticmethod
    def _key_id(api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"date": self._today(), "counts": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"date": self._today(), "counts": {}}
        if not isinstance(payload, dict) or payload.get("date") != self._today():
            return {"date": self._today(), "counts": {}}
        counts = payload.get("counts")
        if not isinstance(counts, dict):
            counts = {}
        return {"date": self._today(), "counts": counts}

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(self.path)

    def is_exhausted(self, api_key: str) -> bool:
        with self._lock:
            state = self._load()
            return int(state["counts"].get(self._key_id(api_key), 0)) >= self.daily_limit

    def reserve(self, api_key: str) -> bool:
        """为一次实际 HTTP 请求预留每日额度。"""
        with self._lock:
            state = self._load()
            key_id = self._key_id(api_key)
            current = int(state["counts"].get(key_id, 0))
            if current >= self.daily_limit:
                return False
            state["counts"][key_id] = current + 1
            self._save(state)
            return True

    def mark_exhausted(self, api_key: str) -> None:
        with self._lock:
            state = self._load()
            state["counts"][self._key_id(api_key)] = self.daily_limit
            self._save(state)


class AlphaVantageError(RuntimeError):
    """Raised when Alpha Vantage returns an API or configuration error."""


class AlphaVantageClient:
    """Alpha Vantage 官方 HTTP API 客户端。"""

    DEFAULT_BASE_URL = "https://www.alphavantage.co/query"
    MIN_REQUEST_INTERVAL_SECONDS = 1.20
    KEY_FAILURE_COOLDOWN_SECONDS = 60.0
    AUTH_FAILURE_COOLDOWN_SECONDS = 600.0

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: Sequence[str] | None = None,
        base_url: str | None = None,
        proxy: str | None = None,
        rate_limit_per_min: int | None = None,
        daily_limit: int | None = None,
        usage_file: str | Path | None = None,
        session: Any | None = None,
        max_retries: int = 2,
        timeout: float = 30.0,
        backoff_factor: float = 1.0,
        min_request_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        data_cfg = load_data_config()
        if api_keys is not None:
            configured_keys = [str(key).strip() for key in api_keys if str(key).strip()]
            if api_key is not None:
                configured_keys.insert(0, api_key.strip())
            self.api_keys = tuple(dict.fromkeys(configured_keys))
        elif api_key is None:
            self.api_keys = data_settings.resolve_alpha_vantage_api_keys()
        else:
            self.api_keys = data_settings.resolve_alpha_vantage_api_keys(api_key)
        self.api_key = self.api_keys[0] if self.api_keys else ""
        self._key_index = 0
        self._key_cooldowns: dict[str, float] = {}
        self._key_lock = threading.Lock()
        self.base_url = base_url or data_settings.alpha_vantage_url or self.DEFAULT_BASE_URL
        self.proxy = data_settings.alpha_vantage_proxy if proxy is None else proxy
        self.max_retries = max(0, int(max_retries))
        self.timeout = timeout
        self.backoff_factor = max(0.0, float(backoff_factor))
        self.min_request_interval = max(0.0, float(min_request_interval))
        self.sleep_fn = sleep_fn
        self.session: Any = session or requests.Session(impersonate="chrome")
        self.session.headers.update({"User-Agent": "stock-finance/alpha-vantage-client"})
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

        configured_rate = data_cfg.rate_limits.alpha_vantage_per_min
        self._rate_limit_per_min = rate_limit_per_min or configured_rate
        self._key_limiters = {
            key: RateLimiter(max_requests=self._rate_limit_per_min) for key in self.api_keys
        }
        self._key_spacing_locks = {key: threading.Lock() for key in self.api_keys}
        self._key_last_request_at: dict[str, float] = {}
        self.rate_limiter = self._key_limiters.get(
            self.api_key, RateLimiter(max_requests=self._rate_limit_per_min)
        )
        configured_daily_limit = getattr(data_cfg.rate_limits, "alpha_vantage_per_day", 25)
        self._daily_limit = daily_limit or configured_daily_limit
        state_path = (
            Path(usage_file)
            if usage_file is not None
            else Path(data_settings.cache_root or data_settings.cache_dir)
            / "sync"
            / "alphavantage_usage.json"
        )
        self.usage_store = AlphaVantageUsageStore(state_path, self._daily_limit)

    @staticmethod
    def _is_daily_quota_message(message: str) -> bool:
        text = message.lower()
        return any(
            marker in text
            for marker in (
                "daily limit reached",
                "daily limit has been reached",
                "daily quota reached",
                "daily quota exceeded",
                "requests per day limit reached",
                "requests per day limit has been reached",
                "requests per day limit exceeded",
                "per day limit reached",
                "per day limit has been reached",
                "per day limit exceeded",
            )
        )

    @staticmethod
    def _is_frequency_message(message: str) -> bool:
        text = message.lower()
        return any(
            marker in text
            for marker in (
                "rate limit",
                "rate-limited",
                "too many requests",
                "call frequency",
                "per second",
                "per minute",
            )
        )

    @staticmethod
    def _is_auth_message(message: str) -> bool:
        text = message.lower()
        return ("invalid" in text or "unauthorized" in text) and "key" in text

    def _select_key(self, excluded: set[str]) -> str | None:
        with self._key_lock:
            now = time.monotonic()
            for offset in range(len(self.api_keys)):
                index = (self._key_index + offset) % len(self.api_keys)
                key = self.api_keys[index]
                if key in excluded or self.usage_store.is_exhausted(key):
                    continue
                if self._key_cooldowns.get(key, 0.0) > now:
                    continue
                self.api_key = key
                self.rate_limiter = self._key_limiters[key]
                return key
        return None

    def _mark_key_failed(self, api_key: str, cooldown_seconds: float) -> None:
        with self._key_lock:
            self._key_cooldowns[api_key] = time.monotonic() + cooldown_seconds
            if api_key in self.api_keys:
                index = self.api_keys.index(api_key)
                self._key_index = (index + 1) % len(self.api_keys)
        logger.warning("Alpha Vantage 当前 Key 请求失败，已暂时熔断 %.0f 秒", cooldown_seconds)

    def _acquire_request_slot(self, api_key: str) -> None:
        """同时遵守每分钟额度和 Alpha Vantage 的单 Key 最小请求间隔。"""
        self._key_limiters[api_key].acquire()
        if self.min_request_interval <= 0:
            return

        spacing_lock = self._key_spacing_locks[api_key]
        with spacing_lock:
            now = time.monotonic()
            last_request_at = self._key_last_request_at.get(api_key)
            if last_request_at is not None:
                delay = self.min_request_interval - (now - last_request_at)
                if delay > 0:
                    logger.info(
                        "Alpha Vantage 单 Key 请求间隔不足，等待 %.2f 秒",
                        delay,
                    )
                    self.sleep_fn(delay)
            self._key_last_request_at[api_key] = time.monotonic()

    def _request(self, params: dict[str, str]) -> dict[str, Any]:
        if not self.api_keys:
            raise AlphaVantageError(
                "缺少 ALPHA_VANTAGE_API_KEY 或 ALPHA_VANTAGE_API_KEYS；"
                "请先配置 Alpha Vantage API key"
            )

        excluded: set[str] = set()
        reserved_keys: set[str] = set()
        last_error: AlphaVantageError | None = None
        while len(excluded) < len(self.api_keys):
            api_key = self._select_key(excluded)
            if api_key is None:
                break
            for attempt in range(self.max_retries + 1):
                if api_key not in reserved_keys:
                    if not self.usage_store.reserve(api_key):
                        break
                    reserved_keys.add(api_key)
                self._acquire_request_slot(api_key)
                request_params = {**params, "apikey": api_key}
                try:
                    response = self.session.get(
                        self.base_url, params=request_params, timeout=self.timeout
                    )
                except Exception as exc:
                    last_error = AlphaVantageError(f"Alpha Vantage 网络请求失败: {exc}")
                    if attempt < self.max_retries:
                        self._sleep_before_retry(attempt, None, exc)
                        continue
                    self._mark_key_failed(api_key, self.KEY_FAILURE_COOLDOWN_SECONDS)
                    break

                status = getattr(response, "status_code", None)
                if isinstance(status, int) and (status == 429 or status >= 500):
                    last_error = AlphaVantageError(f"Alpha Vantage HTTP {status}")
                    if attempt < self.max_retries:
                        self._sleep_before_retry(attempt, response, status)
                        continue
                    self._mark_key_failed(api_key, self.KEY_FAILURE_COOLDOWN_SECONDS)
                    break
                if isinstance(status, int) and status in {401, 403}:
                    last_error = AlphaVantageError(f"Alpha Vantage HTTP {status}，当前 Key 不可用")
                    self._mark_key_failed(api_key, self.AUTH_FAILURE_COOLDOWN_SECONDS)
                    break
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
                    message = str(error_message)
                    last_error = AlphaVantageError(f"Alpha Vantage [Error Message]: {message}")
                    if self._is_auth_message(message):
                        self._mark_key_failed(api_key, self.AUTH_FAILURE_COOLDOWN_SECONDS)
                        break
                    raise last_error

                temporary_message: str | None = None
                for error_key in ("Information", "Note"):
                    raw_message = payload.get(error_key)
                    if raw_message:
                        temporary_message = f"Alpha Vantage [{error_key}]: {raw_message}"
                        break
                if temporary_message is not None:
                    last_error = AlphaVantageError(temporary_message)
                    if self._is_daily_quota_message(temporary_message):
                        self.usage_store.mark_exhausted(api_key)
                        with self._key_lock:
                            self._key_index = (self.api_keys.index(api_key) + 1) % len(
                                self.api_keys
                            )
                        break
                    if attempt < self.max_retries:
                        self._sleep_before_retry(attempt, response, temporary_message)
                        continue
                    if self._is_frequency_message(temporary_message):
                        self._mark_key_failed(api_key, self.KEY_FAILURE_COOLDOWN_SECONDS)
                        break
                    raise last_error
                return payload

            excluded.add(api_key)
        if last_error is not None:
            raise last_error
        raise AlphaVantageError("Alpha Vantage 所有已配置 Key 均不可用或已达到每日额度")

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

    def fetch_daily_raw(self, symbol: str, outputsize: str = "compact") -> dict[str, Any]:
        """Fetch raw daily OHLCV data for a global equity symbol."""
        return self._request(
            {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": outputsize,
            }
        )

    def fetch_company_overview_raw(self, symbol: str) -> dict[str, Any]:
        """Fetch the current company overview and valuation snapshot."""
        return self._request({"function": "OVERVIEW", "symbol": symbol})

    def fetch_earnings_raw(self, symbol: str) -> dict[str, Any]:
        """Fetch annual and quarterly earnings history."""
        return self._request({"function": "EARNINGS", "symbol": symbol})

    def fetch_statement_raw(self, symbol: str, statement_type: str) -> dict[str, Any]:
        """Fetch an annual and quarterly company financial statement."""
        function_by_type = {
            "financials": "INCOME_STATEMENT",
            "income_statement": "INCOME_STATEMENT",
            "balance_sheet": "BALANCE_SHEET",
            "cashflow": "CASH_FLOW",
            "cash_flow": "CASH_FLOW",
        }
        try:
            function = function_by_type[statement_type.lower()]
        except KeyError as exc:
            raise AlphaVantageError(
                f"Unsupported Alpha Vantage statement type: {statement_type}"
            ) from exc
        return self._request({"function": function, "symbol": symbol})

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

    def get(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        """Compatibility entry point for registered Alpha Vantage endpoints."""
        if endpoint.upper() == "TIME_SERIES_DAILY":
            return self.fetch_daily_raw(
                symbol=str(kwargs["symbol"]),
                outputsize=str(kwargs.get("outputsize", "compact")),
            )
        if endpoint.upper() == "OVERVIEW":
            return self.fetch_company_overview_raw(symbol=str(kwargs["symbol"]))
        if endpoint.upper() == "EARNINGS":
            return self.fetch_earnings_raw(symbol=str(kwargs["symbol"]))
        if endpoint.upper() in {
            "INCOME_STATEMENT",
            "BALANCE_SHEET",
            "CASH_FLOW",
        }:
            return self.fetch_statement_raw(symbol=str(kwargs["symbol"]), statement_type=endpoint)
        if endpoint.upper() != "FX_DAILY":
            raise AlphaVantageError(f"Unsupported Alpha Vantage endpoint: {endpoint}")
        return self.fetch_fx_daily_raw(
            from_symbol=str(kwargs["from_symbol"]),
            to_symbol=str(kwargs["to_symbol"]),
            outputsize=str(kwargs.get("outputsize", "full")),
        )
