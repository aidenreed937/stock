from stock.data.cleaner.base import BaseDataCleaner
from stock.data.fetcher.tushare.facade import TuShareDataFetcher
from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.pipeline import MarketDataPipeline

def create_tushare_pipeline(endpoint: str = "stock_daily_bar") -> MarketDataPipeline:
    """按项目任务名创建 TuShare Pipeline。"""
    fetcher = TuShareDataFetcher()
    cleaner: BaseDataCleaner
    from stock.data.task_registry import resolve_task

    task = resolve_task("tushare", endpoint)
    meta = TUSHARE_API_REGISTRY.get(task.api_name)
    if meta and meta.quality_profile == "bar":
        cleaner = BarDataCleaner()
    else:
        p_keys = meta.primary_keys if meta else None
        cleaner = GenericCleaner(primary_keys=p_keys)
    return MarketDataPipeline(
        fetcher=fetcher,
        cleaner=cleaner,
        data_source="tushare",
        endpoint=task.task_name,
    )
