"""基于线程安全的通用滑动窗口速率限制器 (Rate Limiter)。"""

import threading
import time

from stock.utils.logger import logger


class RateLimiter:
    """滑动窗口速率限制器，支持在释放锁后无阻塞休眠。"""

    def __init__(self, max_requests: int, time_window_seconds: float = 60.0) -> None:
        """初始化限制器。

        Args:
            max_requests: 窗口内最大请求次数。
            time_window_seconds: 时间窗口长度 (秒)。
        """
        self.max_requests = max_requests
        self.time_window = time_window_seconds
        self._requests: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """请求一个调用配额，若配额用尽则在释放锁后休眠，醒来后继续竞态配额。"""
        while True:
            sleep_time = 0.0
            with self._lock:
                now = time.monotonic()
                # 清理超出滑动时间窗口的旧请求记录
                self._requests = [t for t in self._requests if now - t < self.time_window]

                if len(self._requests) < self.max_requests:
                    self._requests.append(now)
                    return

                # 配额用尽，计算离最旧请求滑出窗口所需的等待时间
                sleep_time = self.time_window - (now - self._requests[0])

            # 【核心优化】：在锁作用域外部执行休眠，防止阻塞其他线程
            if sleep_time > 0:
                logger.warning(
                    f"RateLimiter 配额用尽 ({self.max_requests}/{self.time_window}s)，"
                    f"释放锁并静默休眠 {sleep_time:.2f} 秒..."
                )
                time.sleep(sleep_time)
