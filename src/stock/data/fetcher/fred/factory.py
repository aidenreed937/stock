"""美联储 (FRED) Pipeline 与 Fetcher 工厂函数模块。"""

from __future__ import annotations

from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.fetcher.fred.client import FredClient
from stock.data.fetcher.fred.global_fetcher import FredDataFetcher
from stock.data.normalizer.generic_normalizer import GenericNormalizer
from stock.data.pipeline import MarketDataPipeline
from stock.data.task_registry import resolve_task


def create_fred_fetcher(proxy: str | None = None) -> FredDataFetcher:
    """创建并初始化 FredDataFetcher 实例。"""
    client = FredClient(proxy=proxy)
    return FredDataFetcher(client=client)


def create_fred_pipeline(
    proxy: str | None = None,
    endpoint: str = "fred_macro",
    fetcher: FredDataFetcher | None = None,
) -> MarketDataPipeline:
    """按项目任务名创建 FRED Pipeline。"""
    active_fetcher = (
        fetcher if fetcher is not None else create_fred_fetcher(proxy=proxy)
    )
    task = resolve_task("fred", endpoint)
    return MarketDataPipeline(
        fetcher=active_fetcher,
        cleaner=GenericCleaner(),
        normalizer=GenericNormalizer(),
        data_source="fred",
        endpoint=task.task_name,
    )
