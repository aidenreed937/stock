"""理杏仁 (Lixinger) Pipeline 与 Fetcher 工厂函数模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock_data.core.task_registry import resolve_task
from stock_data.fetcher.lixinger.facade import LixingerDataFetcher
from stock_data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

if TYPE_CHECKING:
    from stock_data.pipeline.pipeline import MarketDataPipeline


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
    from stock_data.pipeline.cleaner.bar_cleaner import BarDataCleaner
    from stock_data.pipeline.cleaner.base import BaseDataCleaner
    from stock_data.pipeline.cleaner.generic_cleaner import (
        GenericCleaner,
        LixingerIndexFundamentalCleaner,
    )
    from stock_data.pipeline.normalizer import (
        BarDataNormalizer,
        BaseDataNormalizer,
        GenericNormalizer,
    )
    from stock_data.pipeline.pipeline import MarketDataPipeline

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
        nullable_p_keys = meta.nullable_primary_keys if meta else None
        cleaner_cls = (
            LixingerIndexFundamentalCleaner
            if task.dataset == "index_fundamental"
            else GenericCleaner
        )
        cleaner = cleaner_cls(primary_keys=p_keys, nullable_primary_keys=nullable_p_keys)
        normalizer = GenericNormalizer()
    return MarketDataPipeline(
        fetcher=active_fetcher,
        cleaner=cleaner,
        normalizer=normalizer,
        data_source="lixinger",
        endpoint=task.task_name,
    )
