"""美联储 (FRED) Pipeline 与 Fetcher 工厂函数模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock_data.core.task_registry import resolve_task
from stock_data.fetcher.fred.client import FredClient
from stock_data.fetcher.fred.global_fetcher import FredDataFetcher

if TYPE_CHECKING:
    from stock_data.pipeline.pipeline import MarketDataPipeline


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
    from stock_data.pipeline.cleaner.generic_cleaner import GenericCleaner
    from stock_data.pipeline.normalizer.generic_normalizer import GenericNormalizer
    from stock_data.pipeline.pipeline import MarketDataPipeline

    active_fetcher = fetcher if fetcher is not None else create_fred_fetcher(proxy=proxy)
    task = resolve_task("fred", endpoint)
    return MarketDataPipeline(
        fetcher=active_fetcher,
        cleaner=GenericCleaner(),
        normalizer=GenericNormalizer(),
        data_source="fred",
        endpoint=task.task_name,
    )
