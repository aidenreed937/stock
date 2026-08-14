"""Yahoo Finance Pipeline 与 Fetcher 工厂函数模块。"""

from __future__ import annotations

from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.fetcher.yfinance.client import YFinanceClient
from stock.data.fetcher.yfinance.global_fetcher import YFinanceDataFetcher
from stock.data.pipeline import MarketDataPipeline
from stock.data.task_registry import resolve_task


def create_yfinance_fetcher(proxy: str | None = None) -> YFinanceDataFetcher:
    """创建 YFinanceDataFetcher 实例。"""
    client = YFinanceClient(proxy=proxy)
    return YFinanceDataFetcher(client=client)


def create_yfinance_pipeline(
    proxy: str | None = None,
    endpoint: str = "stock_daily_bar",
    fetcher: YFinanceDataFetcher | None = None,
) -> MarketDataPipeline:
    """创建并装配好 YFinance 数据源的 MarketDataPipeline 实例。

    Args:
        proxy: HTTP/HTTPS 代理配置。
        endpoint: 接口标识名称。
        fetcher: 可选的共享 Fetcher 实例。
    """
    active_fetcher = (
        fetcher if fetcher is not None else create_yfinance_fetcher(proxy=proxy)
    )
    task = resolve_task("yfinance", endpoint)
    cleaner = BarDataCleaner() if task.quality_profile == "bar" else None
    return MarketDataPipeline(
        fetcher=active_fetcher,
        cleaner=cleaner,
        data_source="yfinance",
        endpoint=task.task_name,
    )
