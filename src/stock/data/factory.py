"""统一数据管道 (Pipeline) 与数据抓取器 (Fetcher) 共享工厂模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stock.data.fetcher.base import BaseDataFetcher

if TYPE_CHECKING:
    from stock.data.pipeline import MarketDataPipeline

_FETCHER_CACHE: dict[str, BaseDataFetcher] = {}


def clear_fetcher_cache() -> None:
    """清空全局 Fetcher 缓存单例（主要用于测试隔离）。"""
    _FETCHER_CACHE.clear()


def get_shared_fetcher(data_source: str, **kwargs: Any) -> BaseDataFetcher:
    """获取或初始化全局共享的 Fetcher 实例（保障全生命周期共享 RateLimiter 与元数据缓存）。

    Args:
        data_source: 数据源标识 (tushare, lixinger, yfinance, fred).
        **kwargs: 附加初始化参数（如 proxy, token, url 等）。

    Returns:
        BaseDataFetcher: 共享的抓取器单例。
    """
    ds = data_source.lower()
    # 构造唯一缓存键
    cache_key = f"{ds}:{sorted(kwargs.items())}"
    if cache_key in _FETCHER_CACHE:
        return _FETCHER_CACHE[cache_key]

    fetcher: BaseDataFetcher
    if ds == "tushare":
        from stock.data.fetcher.tushare.factory import create_tushare_fetcher

        fetcher = create_tushare_fetcher(
            token=kwargs.get("token"), url=kwargs.get("url")
        )
    elif ds == "lixinger":
        from stock.data.fetcher.lixinger.factory import create_lixinger_fetcher

        fetcher = create_lixinger_fetcher(
            token=kwargs.get("token"), url=kwargs.get("url")
        )
    elif ds == "yfinance":
        from stock.data.fetcher.yfinance.factory import create_yfinance_fetcher

        fetcher = create_yfinance_fetcher(
            proxy=kwargs.get("proxy"),
            proxy_pool_file=kwargs.get("proxy_pool_file"),
        )
    elif ds == "fred":
        from stock.config.settings import settings
        from stock.data.fetcher.fred.factory import create_fred_fetcher

        proxy = kwargs.get("proxy") or getattr(settings, "fred_proxy", None)
        fetcher = create_fred_fetcher(proxy=proxy)
    else:
        from stock.data.fetcher.tushare.factory import create_tushare_fetcher

        fetcher = create_tushare_fetcher()

    _FETCHER_CACHE[cache_key] = fetcher
    return fetcher


def create_pipeline(
    data_source: str,
    endpoint: str = "stock_daily_bar",
    fetcher: BaseDataFetcher | None = None,
) -> MarketDataPipeline:
    """根据数据源名称和项目任务名统一装配 MarketDataPipeline 实例。

    Args:
        data_source: 数据源标识名称（如 tushare, yfinance, lixinger, fred）。
        endpoint: 项目任务名（如 stock_daily_bar、daily_basic）。
        fetcher: 可选的显式 Fetcher 实例；若为 None，则默认使用全局共享 Fetcher 单例。

    Returns:
        MarketDataPipeline: 配置好的行情数据 ETL 管道。
    """
    ds = data_source.lower()
    active_fetcher = fetcher if fetcher is not None else get_shared_fetcher(ds)

    if ds == "tushare":
        from stock.data.fetcher.tushare.facade import TuShareDataFetcher
        from stock.data.fetcher.tushare.factory import create_tushare_pipeline

        tf = active_fetcher if isinstance(active_fetcher, TuShareDataFetcher) else None
        return create_tushare_pipeline(endpoint=endpoint, fetcher=tf)
    elif ds == "lixinger":
        from stock.data.fetcher.lixinger.facade import LixingerDataFetcher
        from stock.data.fetcher.lixinger.factory import create_lixinger_pipeline

        lf = active_fetcher if isinstance(active_fetcher, LixingerDataFetcher) else None
        return create_lixinger_pipeline(endpoint=endpoint, fetcher=lf)
    elif ds == "yfinance":
        from stock.data.fetcher.yfinance.factory import create_yfinance_pipeline
        from stock.data.fetcher.yfinance.global_fetcher import YFinanceDataFetcher

        yf = active_fetcher if isinstance(active_fetcher, YFinanceDataFetcher) else None
        return create_yfinance_pipeline(endpoint=endpoint, fetcher=yf)
    elif ds == "fred":
        from stock.data.fetcher.fred.factory import create_fred_pipeline
        from stock.data.fetcher.fred.global_fetcher import FredDataFetcher

        ff = active_fetcher if isinstance(active_fetcher, FredDataFetcher) else None
        return create_fred_pipeline(endpoint=endpoint, fetcher=ff)
    else:
        from stock.data.fetcher.tushare.facade import TuShareDataFetcher
        from stock.data.fetcher.tushare.factory import create_tushare_pipeline

        tf = active_fetcher if isinstance(active_fetcher, TuShareDataFetcher) else None
        return create_tushare_pipeline(endpoint=endpoint, fetcher=tf)
