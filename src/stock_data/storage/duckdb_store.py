"""基于 DuckDB + Parquet 的本地行情存储仓储门面 (DuckDBMarketStore)。"""

from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from stock_core.constants import BAR_DATASETS
from stock_core.contracts import DatasetKey
from stock_data.core.runtime import DataRuntimeContext
from stock_data.storage.compat import StorageCompat
from stock_data.storage.duckdb_queries import DuckDBQueryMixin
from stock_data.storage.partition_store import ParquetPartitionStore
from stock_data.storage.query_engine import DuckDBQueryEngine


class DuckDBMarketStore(DuckDBQueryMixin):
    """本地行情与衍生数据集存储仓储门面 (MarketDataRepository / Facade)。

    通过组合 ParquetPartitionStore（物理分区与合并落盘）和 DuckDBQueryEngine（SQL 查询与 Arrow 转换），
    实现底层物理 I/O 与高层业务查询的彻底解耦。
    """

    _BAR_DATASETS = BAR_DATASETS

    def __init__(
        self,
        storage_dir: Path | str | None = None,
        data_source: str | None = None,
        *,
        runtime: DataRuntimeContext | None = None,
    ) -> None:
        self.partition_store = ParquetPartitionStore(
            storage_dir=storage_dir, data_source=data_source, runtime=runtime
        )
        self.query_engine = DuckDBQueryEngine()
        self.data_source = self.partition_store.data_source
        self.storage_dir = self.partition_store.storage_dir
        self.conn: duckdb.DuckDBPyConnection = self.query_engine.conn
        self._curated_cache: dict[Path, pl.DataFrame] = self.partition_store._curated_cache

    @staticmethod
    def _is_artifact_path(path: Path) -> bool:
        return StorageCompat.is_artifact_path(path)

    @staticmethod
    def _normalize_identity_columns(df: pl.DataFrame) -> pl.DataFrame:
        return StorageCompat.normalize_identity_columns(df)

    @staticmethod
    def _normalize_datetime_columns(df: pl.DataFrame) -> pl.DataFrame:
        return StorageCompat.normalize_datetime_columns(df)

    def _get_source_dir(self) -> Path:
        return self.partition_store._get_source_dir()

    def _active_parquet_paths(self) -> list[Path]:
        return self.partition_store.active_parquet_paths()

    def _require_data_source(self) -> str:
        return self.partition_store.require_data_source()

    def bind_data_source(self, data_source: str) -> None:
        self.partition_store.bind_data_source(data_source)
        self.data_source = self.partition_store.data_source
        self.storage_dir = self.partition_store.storage_dir

    def enable_batch_mode(self) -> None:
        self.partition_store.enable_batch_mode()

    def commit(self) -> None:
        self.partition_store.commit()

    def _merge_and_save_parquet(
        self, file_path: Path, dfs: list[pl.DataFrame], source: str | None = None
    ) -> pl.DataFrame:
        return self.partition_store._merge_and_save_parquet(file_path, dfs, source=source)

    def _dataset_name(self, endpoint: str, data_source: str | None = None) -> str:
        return self.partition_store._dataset_name(endpoint, data_source=data_source)

    def get_parquet_path(self, endpoint: str, target_date: date, market: str = "MULTI") -> Path:
        return self.partition_store.get_parquet_path(endpoint, target_date, market=market)

    def has_curated(self, endpoint: str, target_date: date, symbol: str | None = None) -> bool:
        return self.partition_store.has_curated(endpoint, target_date, symbol=symbol)

    def save_market_data(
        self,
        endpoint: str,
        target_date: date,
        df: pl.DataFrame,
        data_source: str | None = None,
    ) -> Path:
        return self.partition_store.save_curated(
            df=df, endpoint=endpoint, target_date=target_date, data_source=data_source
        )

    def save_curated(
        self,
        df: pl.DataFrame,
        endpoint: str,
        target_date: date,
        data_source: str | None = None,
    ) -> Path:
        return self.partition_store.save_curated(
            df=df, endpoint=endpoint, target_date=target_date, data_source=data_source
        )

    def save_dataset(self, key: DatasetKey, df: pl.DataFrame) -> Path:
        return self.partition_store.save_dataset(key=key, df=df)

    def query_by_sql(self, sql_query: str) -> pl.DataFrame:
        return self.query_engine.query_by_sql(sql_query)

    def get_max_trade_date(self, symbol: str, endpoint: str = "stock_daily_bar") -> date | None:
        df = self.query_daily_bars(symbol=symbol, endpoint=endpoint)
        if df.is_empty() or "trade_date" not in df.columns:
            return None
        max_d = df["trade_date"].max()
        if isinstance(max_d, date):
            return max_d
        if isinstance(max_d, str):
            return date.fromisoformat(max_d)
        return None

    def query_universe_snapshots(self, as_of_date: date | str | None = None) -> pl.DataFrame:
        snap_dir = self.storage_dir / "universe_snapshots"
        matched_files = [
            str(path) for path in snap_dir.rglob("*.parquet") if not self._is_artifact_path(path)
        ]
        return self.query_engine.query_universe_snapshots(
            matched_files=matched_files, as_of_date=as_of_date
        )
