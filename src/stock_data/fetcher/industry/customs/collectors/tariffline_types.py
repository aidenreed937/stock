"""Tariffline 请求状态、预算与超时控制类型。"""

from __future__ import annotations

import threading
import time
from typing import Any, Literal

TarifflineStatus = Literal["success", "empty", "failed", "truncated", "quota_exhausted"]
_MAX_RECORDS = 100_000
_MAX_API_CALLS = 500
_MIN_CALL_INTERVAL_SECONDS = 5.0
_REQUEST_TIMEOUT_SECONDS = 3_600
_HTTP_CONNECT_TIMEOUT_SECONDS = 30
_TARIFFLINE_API_URL = "https://comtradeapi.un.org/data/v1/getTariffline/C/M/HS"


class TarifflineCallLimitError(RuntimeError):
    """Tariffline 单次运行已用尽 API 调用预算。"""


class TarifflineCallLimiter:
    """在线程间共享的 Tariffline 调用节流器和预算。"""

    def __init__(
        self,
        *,
        max_calls: int = _MAX_API_CALLS,
        min_interval_seconds: float = _MIN_CALL_INTERVAL_SECONDS,
    ) -> None:
        if max_calls < 1:
            raise ValueError("Tariffline max_calls 必须大于 0")
        if min_interval_seconds < 0:
            raise ValueError("Tariffline min_interval_seconds 不能为负数")
        self.max_calls = max_calls
        self.min_interval_seconds = min_interval_seconds
        self._calls = 0
        self._next_call_at = 0.0
        self._lock = threading.Lock()

    @property
    def calls(self) -> int:
        """返回已预留的真实 API 调用次数（重试也计入）。"""
        with self._lock:
            return self._calls

    def acquire(self) -> int:
        """预留下一个调用时隙，保证调用启动间隔和总调用预算。"""
        with self._lock:
            if self._calls >= self.max_calls:
                raise TarifflineCallLimitError(f"Tariffline API 调用已达到上限 {self.max_calls} 次")
            now = time.monotonic()
            scheduled_at = max(now, self._next_call_at)
            self._next_call_at = scheduled_at + self.min_interval_seconds
            self._calls += 1
            call_number = self._calls
        wait_seconds = scheduled_at - now
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        return call_number


class _TarifflineRequestTimeoutError(TimeoutError):
    """单个 Tariffline 请求超过硬超时时间。"""


def _raise_request_timeout(signum: int, frame: Any) -> None:
    del signum, frame
    raise _TarifflineRequestTimeoutError(f"Tariffline 请求超过 {_REQUEST_TIMEOUT_SECONDS} 秒硬超时")


__all__ = [
    "_HTTP_CONNECT_TIMEOUT_SECONDS",
    "_MAX_RECORDS",
    "_REQUEST_TIMEOUT_SECONDS",
    "_TARIFFLINE_API_URL",
    "TarifflineCallLimitError",
    "TarifflineCallLimiter",
    "TarifflineStatus",
    "_raise_request_timeout",
]
