import threading
import time
from typing import Any

import pandas as pd
import tushare as ts

from stock.config.loader import load_data_config
from stock.config.settings import settings
from stock.exceptions import DataFetchError
from stock.utils.logger import logger
from stock.utils.rate_limiter import RateLimiter


class TuShareClient:
    """TuShare 官方 Pro API 底层客户端封装。

    提供 Token 鉴权管理、线程安全滑动窗口限频、多 Worker 并发支持与 DataFetchError 抛出。
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
        """初始化 TuShare 客户端。

        Args:
            token: TuShare API Token。若为 None，则从 settings.tushare_token 中读取。
            url: TuShare API 服务器地址。若为 None，则从 settings.tushare_url 中读取。
            rate_limit_per_min: 每分钟最大请求次数限制。若为 None，则从 settings.tushare_rate_limit_per_min 读取。
            max_workers: 并发采集 Worker 线程数。若为 None，则从 settings.tushare_max_workers 读取。
            max_limit_threshold: 警告单次返回达到服务器截断上限的阈值条数 (默认 6000)。
            paginate_threshold: 触发自动分页的条数阈值 (默认 2000)。
        """
        data_cfg = load_data_config()
        self.token = token if token is not None else settings.tushare_token
        self.url = url if url is not None else settings.tushare_url
        self.rate_limit_per_min = (
            rate_limit_per_min
            if rate_limit_per_min is not None
            else data_cfg.rate_limits.tushare_per_min
        )
        self.max_workers = (
            max_workers
            if max_workers is not None
            else data_cfg.concurrency.tushare_max_workers
        )
        self.max_limit_threshold = max_limit_threshold
        self.paginate_threshold = paginate_threshold

        self.rate_limiter = RateLimiter(max_requests=self.rate_limit_per_min)
        self._pro_api: Any = None

    @property
    def pro(self) -> Any:
        """延迟初始化并返回 TuShare Pro API 实例。

        Raises:
            DataFetchError: 未配置 Token 时抛出。
        """
        if self._pro_api is None:
            if not self.token:
                raise DataFetchError(
                    "未配置 TuShare API Token！请在 .env 文件中设置 TUSHARE_TOKEN=your_token"
                )
            self._pro_api = ts.pro_api(token=self.token)
            if self.url:
                setattr(self._pro_api, "_DataApi__http_url", self.url)
            logger.debug(
                f"TuShare Pro API 初始化成功 [server: {self.url or 'default'}, "
                f"rate_limit: {self.rate_limit_per_min}/min, workers: {self.max_workers}]"
            )
        return self._pro_api

    def query(self, api_name: str, *, auto_paginate: bool = True, **kwargs: Any) -> pd.DataFrame:
        """调用指定 TuShare 接口并返回 Pandas DataFrame (自动做滑动窗口限频与截断防护)。

        Args:
            api_name: TuShare API 接口名（如 daily, fina_indicator）。
            auto_paginate: 是否自动执行 limit/offset 游标分页翻页。
            **kwargs: 传给 API 的查询参数。

        Returns:
            pd.DataFrame: 原始响应数据帧。

        Raises:
            DataFetchError: 接口请求异常或 Token 无效时抛出。
        """
        self.rate_limiter.acquire()
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(
                    f"TuShare 请求 (尝试 {attempt}/{max_retries}): api_name={api_name}, kwargs={kwargs}"
                )
                try:
                    df: pd.DataFrame = self.pro.query(api_name, **kwargs)
                except Exception as ssl_e:
                    err_msg = str(ssl_e)
                    if "ip超限" in err_msg or "频率" in err_msg or "最多" in err_msg:
                        if attempt < max_retries:
                            sleep_sec = attempt * 3.0
                            logger.warning(
                                f"TuShare 触发服务端频控拦截 [{err_msg}]，静默等待 {sleep_sec} 秒后进行第 {attempt + 1} 次自动重试..."
                            )
                            time.sleep(sleep_sec)
                            continue
                        raise
                    if "SSL" in err_msg or "SSLEOFError" in err_msg:
                        logger.warning(f"TuShare HTTPS 请求异常 [{ssl_e}]，降级使用 HTTP 协议重试 [{api_name}]...")
                        current_url = getattr(self.pro, "_DataApi__http_url", "")
                        if current_url.startswith("https://"):
                            http_url = "http://" + current_url[8:]
                            setattr(self.pro, "_DataApi__http_url", http_url)
                            df = self.pro.query(api_name, **kwargs)
                        else:
                            raise
                    else:
                        raise

                if df is None or df.empty:
                    return pd.DataFrame()

                # 截断告警防护：如果单次返回条数达到边界，触发日志警告
                if len(df) >= self.max_limit_threshold and not auto_paginate:
                    logger.warning(
                        f"TuShare 接口 [{api_name}] 单次返回 {len(df)} 条记录，可能已触发服务器 {self.max_limit_threshold} 条截断上限！"
                        f"建议传参 auto_paginate=True 或缩小查询范围。"
                    )

                # 如果启用自动分页翻页 (Cursor Pagination)
                if auto_paginate and len(df) >= self.paginate_threshold:
                    pages = [df]
                    limit = len(df)
                    offset = limit
                    while True:
                        self.rate_limiter.acquire()
                        page_kwargs = dict(kwargs)
                        page_kwargs["limit"] = limit
                        page_kwargs["offset"] = offset
                        page_df: pd.DataFrame = self.pro.query(api_name, **page_kwargs)
                        if page_df is None or page_df.empty:
                            break
                        pages.append(page_df)
                        if len(page_df) < limit:
                            break
                        offset += limit
                    df = pd.concat(pages, ignore_index=True)

                return df
            except Exception as e:
                err_msg = str(e)
                if ("ip超限" in err_msg or "频率" in err_msg or "最多" in err_msg) and attempt < max_retries:
                    sleep_sec = attempt * 3.0
                    logger.warning(
                        f"TuShare 触发服务端频控拦截 [{err_msg}]，静默等待 {sleep_sec} 秒后进行第 {attempt + 1} 次自动重试..."
                    )
                    time.sleep(sleep_sec)
                    continue
                logger.error(f"TuShare API 请求失败 [{api_name}]: {e}")
                raise DataFetchError(f"TuShare 接口 [{api_name}] 请求失败: {e}") from e
        return pd.DataFrame()
