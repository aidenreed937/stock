"""TuShare Pipeline 与 Fetcher 工厂函数模块。"""

from __future__ import annotations

from stock_data.cleaner.bar_cleaner import BarDataCleaner
from stock_data.cleaner.base import BaseDataCleaner
from stock_data.cleaner.generic_cleaner import GenericCleaner
from stock_data.fetcher.tushare.facade import TuShareDataFetcher
from stock_data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
from stock_data.pipeline import MarketDataPipeline
from stock_data.task_registry import resolve_task


def create_tushare_fetcher(token: str | None = None, url: str | None = None) -> TuShareDataFetcher:
    """创建 TuShareDataFetcher 实例。"""
    return TuShareDataFetcher(token=token, url=url)


def create_tushare_pipeline(
    endpoint: str = "stock_daily_bar",
    fetcher: TuShareDataFetcher | None = None,
) -> MarketDataPipeline:
    """按项目任务名创建 TuShare Pipeline。"""
    active_fetcher = fetcher if fetcher is not None else create_tushare_fetcher()
    task = resolve_task("tushare", endpoint)
    meta = TUSHARE_API_REGISTRY.get(task.api_name)
    cleaner: BaseDataCleaner
    if meta and meta.quality_profile == "bar":
        cleaner = BarDataCleaner(listing_dates=BarDataCleaner.load_listing_dates("tushare"))
    else:
        p_keys = meta.primary_keys if meta else None
        cleaner = GenericCleaner(primary_keys=p_keys)
    return MarketDataPipeline(
        fetcher=active_fetcher,
        cleaner=cleaner,
        data_source="tushare",
        endpoint=task.task_name,
    )
