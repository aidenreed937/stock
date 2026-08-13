"""理杏仁 (Lixinger) Pipeline 工厂函数模块。"""

from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.cleaner.base import BaseDataCleaner
from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.fetcher.lixinger.facade import LixingerDataFetcher
from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY
from stock.data.normalizer import BarDataNormalizer, BaseDataNormalizer, GenericNormalizer
from stock.data.pipeline import MarketDataPipeline


def create_lixinger_pipeline(
    endpoint: str = "company_fundamental",
) -> MarketDataPipeline:
    """按项目任务名创建理杏仁 Pipeline。"""
    fetcher = LixingerDataFetcher()
    cleaner: BaseDataCleaner
    normalizer: BaseDataNormalizer
    from stock.data.task_registry import resolve_task

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
        fetcher=fetcher,
        cleaner=cleaner,
        normalizer=normalizer,
        data_source="lixinger",
        endpoint=task.task_name,
    )
