"""理杏仁 (Lixinger) Pipeline 工厂函数模块。"""

from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.cleaner.base import BaseDataCleaner
from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.fetcher.lixinger.facade import LixingerDataFetcher
from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY
from stock.data.pipeline import MarketDataPipeline


def create_lixinger_pipeline(
    endpoint: str = "cn/company/fundamental/non_financial",
) -> MarketDataPipeline:
    """为给定的理杏仁 (Lixinger) 接口创建装配好的 MarketDataPipeline 实例。"""
    fetcher = LixingerDataFetcher()
    cleaner: BaseDataCleaner
    if "candlestick" in endpoint:
        cleaner = BarDataCleaner()
    else:
        meta = LIXINGER_API_REGISTRY.get(endpoint)
        p_keys = meta.primary_keys if meta else None
        cleaner = GenericCleaner(primary_keys=p_keys)
    return MarketDataPipeline(
        fetcher=fetcher,
        cleaner=cleaner,
        data_source="lixinger",
        endpoint=endpoint,
    )
