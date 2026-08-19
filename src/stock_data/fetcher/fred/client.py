import io
import logging
import time
from collections.abc import Callable
from typing import Any

import pandas as pd
from curl_cffi import requests

from stock_core.exceptions import DataFetchError

logger = logging.getLogger(__name__)


class FredClient:
    """FRED (Federal Reserve Economic Data) 官方宏观经济数据客户端。"""

    BASE_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def __init__(
        self,
        proxy: str | None = None,
        max_retries: int = 2,
        timeout: float = 15.0,
        backoff_factor: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        """初始化 FRED 客户端。

        Args:
            proxy: 可选的 HTTP/HTTPS 代理服务配置
            max_retries: 可重试网络或服务端错误的最大次数。
            timeout: 单次 HTTP 请求超时时间（秒）。
            backoff_factor: 指数退避的基础等待时间（秒）。
            sleep_fn: 可注入的等待函数，便于测试。
        """
        self.proxy = proxy
        self.max_retries = max(0, int(max_retries))
        self.timeout = timeout
        self.backoff_factor = max(0.0, float(backoff_factor))
        self.sleep_fn = sleep_fn
        self.session: Any = requests.Session(impersonate="chrome")
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

    def fetch_series_raw(self, series_id: str) -> pd.DataFrame:
        """根据 FRED series_id (如 FEDFUNDS, CPIAUCSL) 下载完整历史数据表。"""
        params = {"id": series_id}
        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(
                    "正在从 FRED 请求宏观序列: %s (%s/%s)...",
                    series_id,
                    attempt + 1,
                    self.max_retries + 1,
                )
                response = self.session.get(self.BASE_CSV_URL, params=params, timeout=self.timeout)
            except Exception as exc:
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt, None, series_id, exc)
                    continue
                logger.error("FRED 请求宏观序列失败 [%s]: %s", series_id, exc)
                raise DataFetchError(
                    f"FRED 请求宏观序列失败 [{series_id}]，重试 {self.max_retries} 次后仍失败: {exc}"
                ) from exc

            status = getattr(response, "status_code", None)
            if isinstance(status, int) and (status == 429 or status >= 500):
                if attempt < self.max_retries:
                    self._sleep_before_retry(attempt, response, series_id, status)
                    continue
                raise DataFetchError(
                    f"FRED 请求宏观序列失败 [{series_id}]，HTTP {status}，"
                    f"重试 {self.max_retries} 次后仍失败"
                )

            try:
                response.raise_for_status()
            except Exception as exc:
                raise DataFetchError(f"FRED 请求宏观序列失败 [{series_id}]: {exc}") from exc

            try:
                # 将 CSV 内容转为 Pandas DataFrame
                csv_file = io.StringIO(response.text)
                df = pd.read_csv(csv_file)
                # FRED 返回字段: observation_date 或 DATE, {series_id}
                df.columns = [c.strip() for c in df.columns]
                date_col = "observation_date" if "observation_date" in df.columns else "DATE"
                if date_col not in df.columns:
                    raise DataFetchError(f"FRED 响应缺少日期列 [{series_id}]")

                if date_col != "DATE":
                    df = df.rename(columns={date_col: "DATE"})

                # 转换数值类型 (处理 '.' 缺失值)
                val_col = series_id.upper()
                if val_col not in df.columns:
                    raise DataFetchError(f"FRED 响应缺少序列列 [{series_id}/{val_col}]")
                df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
                return df.dropna(subset=[val_col])
            except DataFetchError:
                raise
            except Exception as exc:
                raise DataFetchError(f"FRED 响应解析失败 [{series_id}]: {exc}") from exc

        raise DataFetchError(f"FRED 请求宏观序列失败 [{series_id}]")

    def _sleep_before_retry(self, attempt: int, response: Any, series_id: str, detail: Any) -> None:
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
        logger.warning(
            "FRED 请求 [%s] 暂时失败 (%s)，将在 %.2f 秒后重试",
            series_id,
            detail,
            delay,
        )
        self.sleep_fn(delay)

    def get(self, endpoint: str, **kwargs: Any) -> pd.DataFrame:
        """通用查询入口，兼容标准 Client 接口。"""
        return self.fetch_series_raw(series_id=endpoint)
