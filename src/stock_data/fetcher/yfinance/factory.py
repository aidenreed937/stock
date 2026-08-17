"""Yahoo Finance Pipeline 与 Fetcher 工厂函数模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock_data.core.task_registry import resolve_task
from stock_data.fetcher.yfinance.client import YFinanceClient
from stock_data.fetcher.yfinance.global_fetcher import YFinanceDataFetcher

if TYPE_CHECKING:
    from pathlib import Path

    from stock_data.pipeline.pipeline import MarketDataPipeline


def create_yfinance_fetcher(
    proxy: str | None = None,
    proxy_pool_file: str | Path | None = None,
) -> YFinanceDataFetcher:
    """创建 YFinanceDataFetcher 实例。"""
    client = YFinanceClient(proxy=proxy, proxy_pool_file=proxy_pool_file)
    return YFinanceDataFetcher(client=client)


def create_yfinance_pipeline(
    proxy: str | None = None,
    endpoint: str = "stock_daily_bar",
    fetcher: YFinanceDataFetcher | None = None,
    proxy_pool_file: str | Path | None = None,
) -> MarketDataPipeline:
    """创建并装配好 YFinance 数据源的 MarketDataPipeline 实例。

    Args:
        proxy: HTTP/HTTPS 代理配置。
        endpoint: 接口标识名称。
        fetcher: 可选的共享 Fetcher 实例。
        proxy_pool_file: 本地代理池文件或目录。
    """
    from stock_data.pipeline.cleaner.bar_cleaner import BarDataCleaner
    from stock_data.pipeline.pipeline import MarketDataPipeline

    active_fetcher = (
        fetcher
        if fetcher is not None
        else create_yfinance_fetcher(proxy=proxy, proxy_pool_file=proxy_pool_file)
    )
    task = resolve_task("yfinance", endpoint)
    cleaner = BarDataCleaner() if task.quality_profile == "bar" else None
    return MarketDataPipeline(
        fetcher=active_fetcher,
        cleaner=cleaner,
        data_source="yfinance",
        endpoint=task.task_name,
    )
