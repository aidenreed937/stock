"""DuckDBMarketStore 的数据集查询职责。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger
from stock_data.governance.quality.margin_coverage import filter_complete_margin_dates
from stock_data.storage.compat import StorageCompat
from stock_data.storage.partition_store import ParquetPartitionStore
from stock_data.storage.query_engine import DuckDBQueryEngine


def _matches_dataset_alias(path: Path, aliases: tuple[str, ...]) -> bool:
    path_parts = {part.casefold() for part in path.parts}
    return any(alias.casefold() in path_parts for alias in aliases)


class DuckDBQueryMixin:
    """提供历史数据集、行情和标的查询。"""

    partition_store: ParquetPartitionStore
    query_engine: DuckDBQueryEngine
    storage_dir: Path

    def query_dataset(
        self,
        dataset: str = "stock_daily_bar",
        symbol: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        data_source = self.partition_store.require_data_source()
        target_dataset = self.partition_store._dataset_name(dataset)
        dataset_aliases = StorageCompat.dataset_aliases(dataset, data_source)
        query_symbol = symbol or StorageCompat.dataset_symbol_filter(dataset, data_source)
        matched_files = [
            str(path)
            for path in self.partition_store.active_parquet_paths()
            if _matches_dataset_alias(path, dataset_aliases)
        ]
        result = self.query_engine.query_dataset(
            matched_files=matched_files,
            symbol=query_symbol,
            start_date=start_date,
            end_date=end_date,
            dataset_name=target_dataset,
            data_source=data_source,
        )
        if data_source == "tushare" and target_dataset == "margin":
            return filter_complete_margin_dates(result, start_date=start_date, end_date=end_date)
        return result

    def query_daily_bars(
        self, symbol: str, endpoint: str = "stock_daily_bar", min_price: float | None = None
    ) -> pl.DataFrame:
        data_source = self.partition_store.require_data_source()
        target_endpoint = self.partition_store._dataset_name(endpoint)
        if target_endpoint == "stock_daily_bar":
            return self.query_dataset(dataset=target_endpoint, symbol=symbol)
        matched_files = [
            str(path)
            for path in self.partition_store.active_parquet_paths()
            if _matches_dataset_alias(path, StorageCompat.dataset_aliases(endpoint, data_source))
        ]
        if not matched_files:
            logger.warning(f"本地无 {target_endpoint} 分区 Parquet 缓存文件")
            return pl.DataFrame()
        return self.query_engine.query_daily_bars(
            matched_files=matched_files,
            symbol=symbol,
            data_source=data_source,
            min_price=min_price,
            dataset_name=target_endpoint,
        )

    def query_history(
        self,
        endpoint: str = "stock_daily_bar",
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
    ) -> pl.DataFrame:
        data_source = self.partition_store.require_data_source()
        target_endpoint = self.partition_store._dataset_name(endpoint)
        if target_endpoint == "stock_daily_bar":
            result = self.query_dataset(
                dataset=target_endpoint,
                start_date=start_date,
                end_date=end_date,
            )
            if symbols:
                result = result.filter(pl.col("symbol").is_in(symbols))
            return result

        query_symbols = symbols
        alias_symbol = StorageCompat.dataset_symbol_filter(endpoint, data_source)
        if alias_symbol:
            if symbols is not None and alias_symbol not in symbols:
                return pl.DataFrame()
            query_symbols = [alias_symbol]
        matched_files = [
            str(path)
            for path in self.partition_store.active_parquet_paths()
            if _matches_dataset_alias(path, StorageCompat.dataset_aliases(endpoint, data_source))
        ]
        if not matched_files:
            logger.warning(f"本地无 {target_endpoint} 分区 Parquet 缓存文件")
            return pl.DataFrame()
        result = self.query_engine.query_history(
            matched_files=matched_files,
            data_source=data_source,
            start_date=start_date,
            end_date=end_date,
            symbols=query_symbols,
            dataset_name=target_endpoint,
        )
        if data_source == "tushare" and target_endpoint == "margin":
            return filter_complete_margin_dates(result, start_date=start_date, end_date=end_date)
        return result
