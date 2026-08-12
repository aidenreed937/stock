from stock.data.fetcher.tushare.facade import TuShareDataFetcher
from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.pipeline import MarketDataPipeline

def create_tushare_pipeline(endpoint: str = "daily") -> MarketDataPipeline:
    """为给定的 TuShare 接口创建装配好的 MarketDataPipeline 实例。"""
    fetcher = TuShareDataFetcher()
    if endpoint == "daily":
        cleaner = BarDataCleaner()
    else:
        meta = TUSHARE_API_REGISTRY.get(endpoint)
        p_keys = meta.primary_keys if meta else None
        cleaner = GenericCleaner(primary_keys=p_keys)
    return MarketDataPipeline(
        fetcher=fetcher,
        cleaner=cleaner,
        data_source="tushare",
        endpoint=endpoint,
    )
