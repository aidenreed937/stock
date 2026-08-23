import threading
import time
from typing import Any

import pandas as pd
import tushare as ts

from stock_core.config.loader import load_data_config
from stock_core.exceptions import DataFetchError
from stock_core.utils.logger import logger
from stock_data.core.settings import data_settings
from stock_data.fetcher.rate_limiter import RateLimiter

_RATE_LIMIT_KEYWORDS = ("ip超限", "频率", "最多", "速度过快", "超限", "频繁", "每分钟")


class TuShareClient:
    """TuShare 官方 Pro API 底层客户端封装。

    支持滑动窗口限频（线程安全）、网络重试与超时退避机制。
    """

    def __init__(
        self,
        token: str | None = None,
        url: str | None = None,
        rate_limit_per_min: int | None = None,
        max_workers: int | None = None,
        max_limit_threshold: int = 6000,
        paginate_threshold: int = 2000,
    ) -> None:
        data_cfg = load_data_config()
        self.token = token if token is not None else data_settings.tushare_token
        self.url = url if url is not None else data_settings.tushare_url
        self.rate_limit_per_min = (
            rate_limit_per_min
            if rate_limit_per_min is not None
            else data_cfg.rate_limits.tushare_per_min
        )
        self.max_workers = (
            max_workers if max_workers is not None else data_cfg.concurrency.tushare_max_workers
        )
        self.max_limit_threshold = max_limit_threshold
        self.paginate_threshold = paginate_threshold

        self.rate_limiter = RateLimiter(max_requests=self.rate_limit_per_min)
        self._pro_api: Any = None
        self._pro_lock = threading.Lock()

    @property
    def pro(self) -> Any:
        if self._pro_api is None:
            with self._pro_lock:
                if self._pro_api is None:
                    if not self.token:
                        raise DataFetchError(
                            "未配置 TuShare API Token！请在 .env 文件中设置 TUSHARE_TOKEN=your_token"
                        )
                    self._pro_api = ts.pro_api(token=self.token)
                    if self.url:
                        self._pro_api._DataApi__http_url = self.url
                    self._pro_api._DataApi__timeout = 60
                    logger.debug(
                        f"TuShare Pro API 初始化成功 [server: {self.url or 'default'}, "
                        f"rate_limit: {self.rate_limit_per_min}/min, workers: {self.max_workers}, timeout: 60s]"
                    )
        return self._pro_api

    def _raw_query(self, api_name: str, **kwargs: Any) -> pd.DataFrame:
        """执行单次底层 TuShare 请求，包含网络超时、频控与连接异常自动重试。"""
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            self.rate_limiter.acquire()
            try:
                logger.debug(
                    f"TuShare 请求 (尝试 {attempt}/{max_retries}): api_name={api_name}, kwargs={kwargs}"
                )
                try:
                    df = self.pro.query(api_name, **kwargs)
                except Exception as req_e:
                    err_msg = str(req_e)
                    if "SSL" in err_msg or "SSLEOFError" in err_msg:
                        logger.warning(
                            f"TuShare HTTPS 请求异常 [{req_e}]，降级使用 HTTP 协议重试 [{api_name}]..."
                        )
                        current_url = getattr(self.pro, "_DataApi__http_url", "")
                        if current_url.startswith("https://"):
                            self.pro._DataApi__http_url = "http://" + current_url[8:]
                            df = self.pro.query(api_name, **kwargs)
                        else:
                            raise
                    else:
                        raise
                return df if df is not None else pd.DataFrame()
            except Exception as e:
                err_msg = str(e)
                if any(kw in err_msg for kw in _RATE_LIMIT_KEYWORDS):
                    if attempt < max_retries:
                        sleep_sec = max(15.0, attempt * 10.0)
                        logger.warning(
                            f"TuShare 触发服务端频控拦截 [{err_msg}]，静默等待 {sleep_sec} 秒后进行第 {attempt + 1} 次重试..."
                        )
                        time.sleep(sleep_sec)
                        continue
                elif attempt < max_retries and not (
                    "token" in err_msg.lower() and ("无效" in err_msg or "不存在" in err_msg)
                ):
                    sleep_sec = attempt * 2.0
                    logger.warning(
                        f"TuShare 接口 [{api_name}] 请求异常 [{e}]，等待 {sleep_sec} 秒后进行第 {attempt + 1} 次重试..."
                    )
                    time.sleep(sleep_sec)
                    continue
                logger.error(f"TuShare API 请求失败 [{api_name}]: {e}")
                raise DataFetchError(f"TuShare 接口 [{api_name}] 请求失败: {e}") from e
        return pd.DataFrame()
        return pd.DataFrame()

    def query(
        self,
        api_name: str,
        *,
        auto_paginate: bool = True,
        pagination_limit: int | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """调用指定 TuShare 接口并返回 Pandas DataFrame (自动做滑动窗口限频、单页重试与截断防护)。

        Args:
            api_name: TuShare API 接口名（如 daily, fina_indicator）。
            auto_paginate: 是否自动执行 limit/offset 游标分页翻页。
            pagination_limit: 端点单页上限；用于识别低于默认分页阈值的截断响应。
            **kwargs: 传给 API 的查询参数。

        Returns:
            pd.DataFrame: 原始响应数据帧。

        Raises:
            DataFetchError: 接口请求异常或 Token 无效时抛出。
        """
        df = self._raw_query(api_name, **kwargs)
        if df.empty:
            return df

        # 截断告警防护：如果单次返回条数达到边界，触发日志警告
        if len(df) >= self.max_limit_threshold and not auto_paginate:
            logger.warning(
                f"TuShare 接口 [{api_name}] 单次返回 {len(df)} 条记录，可能已触发服务器 {self.max_limit_threshold} 条截断上限！"
                f"建议传参 auto_paginate=True 或缩小查询范围。"
            )

        # 如果启用自动分页翻页 (Cursor Pagination)
        pagination_threshold = pagination_limit or self.paginate_threshold
        if auto_paginate and len(df) >= pagination_threshold:
            pages = [df]
            seen_signatures: set[tuple[int, Any, Any]] = {
                (len(df), tuple(df.iloc[0].values), tuple(df.iloc[-1].values))
            }
            limit = len(df)
            offset = limit
            while True:
                page_kwargs = dict(kwargs)
                page_kwargs["limit"] = limit
                page_kwargs["offset"] = offset
                page_df = self._raw_query(api_name, **page_kwargs)
                if page_df.empty:
                    break
                sig = (len(page_df), tuple(page_df.iloc[0].values), tuple(page_df.iloc[-1].values))
                if sig in seen_signatures:
                    logger.debug(
                        f"TuShare 接口 [{api_name}] 分页已达末尾 (offset={offset} 返回重复页)，正常结束翻页。"
                    )
                    break
                seen_signatures.add(sig)
                pages.append(page_df)
                if len(page_df) < limit:
                    break
                offset += limit
            df = pd.concat(pages, ignore_index=True)

        return df
