"""stock_data: 2-Tier 量化金融数据中台 (RAW/Curated ETL, Storage, Fetcher, Pipeline, Governance, Catalog)."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stock_data.catalog.service import DataCatalog
    from stock_data.core.factory import create_pipeline, get_shared_fetcher
    from stock_data.core.settings import DataSettings, data_settings
    from stock_data.fetcher.base import BaseDataFetcher
    from stock_data.pipeline.backfill import HistoricalBackfiller
    from stock_data.pipeline.pipeline import MarketDataPipeline
    from stock_data.pipeline.sync import DailySyncEngine
    from stock_data.storage.duckdb_store import DuckDBMarketStore
    from stock_data.storage.raw_store import RawDataStorage

__all__ = [
    "BaseDataFetcher",
    "DailySyncEngine",
    "DataCatalog",
    "DataSettings",
    "DuckDBMarketStore",
    "HistoricalBackfiller",
    "MarketDataPipeline",
    "RawDataStorage",
    "create_pipeline",
    "data_settings",
    "get_shared_fetcher",
]

_EXPORT_MAP: dict[str, tuple[str, str]] = {
    "BaseDataFetcher": ("stock_data.fetcher.base", "BaseDataFetcher"),
    "DailySyncEngine": ("stock_data.pipeline.sync", "DailySyncEngine"),
    "DataCatalog": ("stock_data.catalog.service", "DataCatalog"),
    "DataSettings": ("stock_data.core.settings", "DataSettings"),
    "DuckDBMarketStore": ("stock_data.storage.duckdb_store", "DuckDBMarketStore"),
    "HistoricalBackfiller": ("stock_data.pipeline.backfill", "HistoricalBackfiller"),
    "MarketDataPipeline": ("stock_data.pipeline.pipeline", "MarketDataPipeline"),
    "RawDataStorage": ("stock_data.storage.raw_store", "RawDataStorage"),
    "create_pipeline": ("stock_data.core.factory", "create_pipeline"),
    "data_settings": ("stock_data.core.settings", "data_settings"),
    "get_shared_fetcher": ("stock_data.core.factory", "get_shared_fetcher"),
}


def __getattr__(name: str) -> Any:
    if name in _EXPORT_MAP:
        mod_name, attr_name = _EXPORT_MAP[name]
        import importlib

        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
