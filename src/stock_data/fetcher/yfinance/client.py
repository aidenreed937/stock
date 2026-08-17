import os
import random
import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from stock_core.config.loader import load_data_config
from stock_core.utils.logger import logger
from stock_data.fetcher.rate_limiter import RateLimiter
from stock_data.settings import data_settings

YFINANCE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
_RETRY_DELAY_SECONDS = 1.0
_RATE_LIMIT_RETRY_DELAY_SECONDS = 5.0
_MAX_RETRY_DELAY_SECONDS = 60.0


def _load_proxy_pool(path: Path) -> tuple[str, ...]:
    """从本地代理池文件读取出口地址，忽略空行与注释。"""
    if path.is_dir():
        named_file = path / "yfinance.txt"
        candidates = [named_file] if named_file.is_file() else sorted(path.glob("*.txt"))
    else:
        candidates = [path]

    proxies: list[str] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning(f"读取 YFinance 代理池失败 [{candidate}]: {exc}")
            continue

        for line in lines:
            proxy = line.split("#", 1)[0].strip()
            if proxy and "://" not in proxy:
                proxy = f"http://{proxy}"
            if proxy:
                proxies.append(proxy)

    return tuple(dict.fromkeys(proxies))


def _is_rate_limited(error: Exception) -> bool:
    """识别 Yahoo 429/限流异常。"""
    status_code = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    status_code = status_code or getattr(response, "status_code", None)
    message = str(error).lower()
    return status_code == 429 or "too many requests" in message or "rate limited" in message


def _retry_after_seconds(error: Exception | None) -> float | None:
    """读取异常中可用的 Retry-After 秒数或 HTTP 日期。"""
    if error is None:
        return None
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", None)
    if not headers:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return float(max(0.0, (retry_at - datetime.now(UTC)).total_seconds()))


def _retry_delay_seconds(attempt: int, error: Exception | None) -> float:
    """计算带随机抖动的指数退避等待时间。"""
    retry_after = _retry_after_seconds(error)
    if retry_after is not None:
        return min(_MAX_RETRY_DELAY_SECONDS, retry_after)

    base_delay = (
        _RATE_LIMIT_RETRY_DELAY_SECONDS
        if error is not None and _is_rate_limited(error)
        else _RETRY_DELAY_SECONDS
    )
    exponential_delay = min(_MAX_RETRY_DELAY_SECONDS, base_delay * (2**attempt))
    jitter = random.uniform(0.0, min(1.0, exponential_delay * 0.25))
    return float(min(_MAX_RETRY_DELAY_SECONDS, exponential_delay + jitter))


class YFinanceClient:
    """Yahoo Finance 客户端包装器。

    支持滑动窗口限频（防 429 反爬封禁）与代理配置。
    """

    MAX_ATTEMPTS = 3
    RETRY_DELAY_SECONDS = _RETRY_DELAY_SECONDS
    RATE_LIMIT_RETRY_DELAY_SECONDS = _RATE_LIMIT_RETRY_DELAY_SECONDS
    MAX_RETRY_DELAY_SECONDS = _MAX_RETRY_DELAY_SECONDS
    PROXY_COOLDOWN_SECONDS = 30.0
    RATE_LIMIT_PROXY_COOLDOWN_SECONDS = 120.0

    def __init__(
        self,
        proxy: str | None = None,
        rate_limit_per_min: int | None = None,
        proxy_pool_file: str | Path | None = None,
    ) -> None:
        """初始化 YFinance 客户端。

        Args:
            proxy: HTTP/HTTPS 代理服务器地址。若为 None，优先读取代理池文件，
                代理池不可用时使用 data_settings.yfinance_proxy。
            rate_limit_per_min: 每分钟最大请求次数限制。若为 None，使用
                config/data.yaml 中的 yfinance_per_min。
            proxy_pool_file: 本地代理池文件或目录。目录默认读取其中的 yfinance.txt。
        """
        data_cfg = load_data_config()
        configured_proxy = ""
        proxy_pool: tuple[str, ...] = ()
        if proxy is not None:
            configured_proxy = proxy
            proxy_pool = (configured_proxy,) if configured_proxy else ("",)
        else:
            pool_path = (
                Path(proxy_pool_file)
                if proxy_pool_file is not None
                else data_settings.yfinance_proxy_pool_file
            )
            proxy_pool = _load_proxy_pool(pool_path)
            if not proxy_pool and data_settings.yfinance_proxy:
                configured_proxy = data_settings.yfinance_proxy
                proxy_pool = (configured_proxy,)
        self.proxy = configured_proxy or None
        self.proxy_pool = proxy_pool or ("",)
        self._proxy_index = os.getpid() % len(self.proxy_pool)
        self._proxy_lock = threading.Lock()
        self._proxy_unavailable_until: dict[str, float] = {}
        rate_limit = (
            rate_limit_per_min
            if rate_limit_per_min is not None
            else data_cfg.rate_limits.yfinance_per_min
        )
        self.rate_limiter = RateLimiter(max_requests=rate_limit)

    def _next_proxy(self) -> str:
        """按轮询选择健康出口，所有出口熔断时等待最早恢复的出口。"""
        with self._proxy_lock:
            now = time.monotonic()
            selected = self.proxy_pool[0]
            wait_until = now
            for _ in self.proxy_pool:
                candidate = self.proxy_pool[self._proxy_index]
                self._proxy_index = (self._proxy_index + 1) % len(self.proxy_pool)
                unavailable_until = self._proxy_unavailable_until.get(candidate, 0.0)
                if unavailable_until <= now:
                    return candidate
                if unavailable_until < wait_until or wait_until == now:
                    selected = candidate
                    wait_until = unavailable_until

        if len(self.proxy_pool) == 1:
            return selected

        wait_seconds = max(0.0, wait_until - time.monotonic())
        if wait_seconds:
            logger.warning(f"YFinance 代理池暂时无可用出口，等待 {wait_seconds:.1f} 秒...")
            time.sleep(wait_seconds)
        return selected

    def _mark_proxy_failed(self, proxy: str, cooldown_seconds: float | None = None) -> None:
        """短暂熔断失败出口，避免重试继续命中同一代理。"""
        if not proxy:
            return
        cooldown = cooldown_seconds or self.PROXY_COOLDOWN_SECONDS
        with self._proxy_lock:
            self._proxy_unavailable_until[proxy] = time.monotonic() + cooldown
        logger.warning(f"YFinance 当前代理请求失败，已熔断 {cooldown:.0f} 秒")

    def _get_session(self, proxy: str | None = None) -> Any:
        """创建具备 Chrome TLS 指纹伪装与代理支持的 Session。"""
        active_proxy = self._next_proxy() if proxy is None else proxy
        try:
            from curl_cffi import requests as curl_requests

            c_session: Any = curl_requests.Session(impersonate="chrome")
            c_session.headers.update({"User-Agent": YFINANCE_USER_AGENT})
            if active_proxy:
                c_session.proxies = {"http": active_proxy, "https": active_proxy}
            return c_session
        except Exception as e:
            logger.debug(f"未能使用 curl_cffi 伪装指纹: {e}")

        import requests

        r_session = requests.Session()
        r_session.headers.update({"User-Agent": YFINANCE_USER_AGENT})
        if active_proxy:
            r_session.proxies = {"http": active_proxy, "https": active_proxy}
        return r_session

    def _query_history_once(
        self,
        symbol: str,
        start_date_str: str,
        end_date_str: str,
        proxy: str,
        history_options: dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        session = self._get_session(proxy)
        ticker = yf.Ticker(symbol, session=session)
        history_kwargs: dict[str, Any] = {
            "start": start_date_str,
            "end": end_date_str,
            "interval": "1d",
        }
        if history_options:
            history_kwargs.update(history_options)
        return ticker.history(**history_kwargs)

    def query_history(
        self,
        symbol: str,
        start_date_str: str,
        end_date_str: str,
        *,
        auto_adjust: bool | None = None,
        repair: bool | None = None,
    ) -> pd.DataFrame:
        """调用 yfinance 接口拉取历史行情。

        Args:
            symbol: 标的代码。
            start_date_str: 开始日期字符串 (YYYY-MM-DD)。
            end_date_str: 结束日期字符串 (YYYY-MM-DD)。
            auto_adjust: 是否使用 yfinance 自动复权；None 表示采用上游默认值。
            repair: 是否启用 yfinance 的历史价格修复。
        """
        last_result = pd.DataFrame()
        last_error: Exception | None = None
        history_options = {
            key: value
            for key, value in {
                "auto_adjust": auto_adjust,
                "repair": repair,
            }.items()
            if value is not None
        }
        for attempt in range(self.MAX_ATTEMPTS):
            self.rate_limiter.acquire()
            proxy = self._next_proxy()
            try:
                last_result = self._query_history_once(
                    symbol,
                    start_date_str,
                    end_date_str,
                    proxy,
                    history_options=history_options,
                )
                last_error = None
                if not last_result.empty:
                    return last_result
                logger.warning(f"YFinance 返回空数据 [{symbol}]，准备切换代理重试")
            except Exception as error:
                last_error = error
                rate_limited = _is_rate_limited(error)
                cooldown = (
                    self.RATE_LIMIT_PROXY_COOLDOWN_SECONDS
                    if rate_limited
                    else self.PROXY_COOLDOWN_SECONDS
                )
                self._mark_proxy_failed(proxy, cooldown_seconds=cooldown)
                logger.warning(f"Yahoo Finance Session 抓取异常 ({error})")

            if attempt + 1 >= self.MAX_ATTEMPTS:
                break
            delay = _retry_delay_seconds(attempt, last_error)
            logger.warning(
                f"Yahoo Finance 将在 {delay:.1f} 秒后重试 ({attempt + 2}/{self.MAX_ATTEMPTS})"
            )
            time.sleep(delay)

        if last_error is not None:
            raise last_error
        return last_result
