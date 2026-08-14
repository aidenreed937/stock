"""理杏仁 (Lixinger) Pipeline 与 Fetcher 工厂函数模块。"""

from __future__ import annotations

from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.cleaner.base import BaseDataCleaner
from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.fetcher.lixinger.facade import LixingerDataFetcher
from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY
from stock.data.normalizer import BarDataNormalizer, BaseDataNormalizer, GenericNormalizer
from stock.data.pipeline import MarketDataPipeline
from stock.data.task_registry import resolve_task


def create_lixinger_fetcher(
    token: str | None = None, url: str | None = None
) -> LixingerDataFetcher:
    """创建 LixingerDataFetcher 实例。"""
    return LixingerDataFetcher(token=token, url=url)


def create_lixinger_pipeline(
    endpoint: str = "company_fundamental",
    fetcher: LixingerDataFetcher | None = None,
) -> MarketDataPipeline:
    """按项目任务名创建理杏仁 Pipeline。"""
    active_fetcher = fetcher if fetcher is not None else create_lixinger_fetcher()
    cleaner: BaseDataCleaner
    normalizer: BaseDataNormalizer

    task = resolve_task("lixinger", endpoint)
    if task.quality_profile == "bar":
        cleaner = BarDataCleaner()
        normalizer = BarDataNormalizer()
    else:
        meta = LIXINGER_API_REGISTRY.get(task.api_name)
        p_keys = meta.primary_keys if meta else None
        cleaner = GenericCleaner(primary_keys=p_keys)
        normalizer = GenericNormalizer()
    return MarketDataPipeline(
        fetcher=active_fetcher,
        cleaner=cleaner,
        normalizer=normalizer,
        data_source="lixinger",
        endpoint=task.task_name,
    )
