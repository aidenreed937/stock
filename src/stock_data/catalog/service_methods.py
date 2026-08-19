"""DataCatalog 的数据读取与摘要方法。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger
from stock_data.catalog.models import CatalogDataset
from stock_data.catalog.ops import (
    build_catalog_summary as _build_catalog_summary,
)
from stock_data.catalog.ops import (
    dataset_name as _dataset_name,
)
from stock_data.catalog.ops import (
    list_parquet_files as _list_parquet_files,
)
from stock_data.catalog.ops import (
    read_dataset_files as _read_dataset_files,
)
from stock_data.catalog.ops import (
    resolve_dataset_alias as _resolve_dataset_alias,
)
from stock_data.catalog.ops import (
    validate_bars as _validate_bars,
)
from stock_data.catalog.summary import build_catalog_description as _build_catalog_description
from stock_data.catalog.watermarks import (
    scan_latest_refresh_dates as _scan_latest_refresh_dates,
)
from stock_data.catalog.watermarks import (
    scan_latest_trade_dates as _scan_latest_trade_dates,
)
from stock_data.storage.compat import StorageCompat


class CatalogReadMixin:
    """提供目录文件发现、读取、水位和摘要操作。"""

    data_source: str
    storage_dir: Path

    def _parquet_files(self, dataset: str | None = None, market: str | None = None) -> list[Path]:
        source_dir = self.storage_dir / self.data_source
        if dataset is None:
            return _list_parquet_files(source_dir, market=market)
        files: set[Path] = set()
        for alias in StorageCompat.dataset_aliases(dataset, self.data_source):
            files.update(_list_parquet_files(source_dir, dataset=alias, market=market))
        return sorted(files)

    def available_datasets(self, market: str | None = None) -> list[CatalogDataset]:
        """列出当前数据源下所有可用数据集。"""
        seen: dict[str, list[Path]] = {}
        for path in self._parquet_files(market=market):
            seen.setdefault(_dataset_name(path), []).append(path)
        return [
            CatalogDataset(data_source=self.data_source, dataset=name, files=tuple(sorted(paths)))
            for name, paths in sorted(seen.items())
        ]

    def load_dataset(
        self,
        dataset: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        market: str | None = None,
        symbols: list[str] | None = None,
        columns: Sequence[str] | None = None,
        dedup: bool = True,
    ) -> pl.DataFrame:
        """读取标准数据集，可按标的与日期范围过滤并投影列。"""
        resolved = _resolve_dataset_alias(self.data_source, dataset)
        files = self._parquet_files(dataset=dataset, market=market)
        alias_symbol = StorageCompat.dataset_symbol_filter(dataset, self.data_source)
        effective_symbols = symbols
        if alias_symbol:
            if symbols is not None and alias_symbol not in symbols:
                return pl.DataFrame()
            effective_symbols = [alias_symbol]
        df = _read_dataset_files(
            files,
            resolved,
            self.data_source,
            start_date,
            end_date,
            effective_symbols,
            columns=columns,
        )
        if dedup and (
            k := StorageCompat.resolve_dedup_keys(resolved, self.data_source, self.data_source, df)
        ):
            if all(col in df.columns for col in k):
                df = df.unique(subset=k, keep="last")
        if columns is not None and not df.is_empty():
            df = df.select([column for column in columns if column in df.columns])
        return df

    def load_bars(
        self,
        symbol: str | None = None,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        symbols: list[str] | None = None,
        columns: Sequence[str] | None = None,
        dataset: str = "stock_daily_bar",
        market: str | None = None,
        adjustment: str | None = None,
        dedup: bool = True,
        validate: bool = True,
    ) -> pl.DataFrame:
        """读取行情数据并进行时序排序与有效性校验。"""
        resolved = _resolve_dataset_alias(self.data_source, dataset)
        alias_symbol = StorageCompat.dataset_symbol_filter(dataset, self.data_source)
        if alias_symbol:
            if symbol is not None and symbol != alias_symbol:
                return pl.DataFrame()
            if symbols is not None and alias_symbol not in symbols:
                return pl.DataFrame()
            symbols = [alias_symbol]
        elif symbol is not None:
            symbols = [symbol]
        df = _read_dataset_files(
            self._parquet_files(dataset=dataset, market=market),
            resolved,
            self.data_source,
            start_date,
            end_date,
            symbols,
            columns=columns,
        )
        if df.is_empty():
            logger.warning(f"DataCatalog 未找到 [{resolved}] 行情数据 (数据源: {self.data_source})")
            return df
        if adjustment is not None and "adjustment" in df.columns:
            df = df.filter(pl.col("adjustment") == adjustment)
        if dedup and "symbol" in df.columns and "trade_date" in df.columns:
            dedup_cols = [
                column for column in ("market", "symbol", "trade_date") if column in df.columns
            ]
            if dedup_cols:
                df = df.unique(subset=dedup_cols, keep="last")
        if "trade_date" in df.columns:
            df = df.sort([column for column in ("trade_date", "symbol") if column in df.columns])
        if validate:
            _validate_bars(df, resolved)
        if columns is not None and not df.is_empty():
            df = df.select([column for column in columns if column in df.columns])
        return df

    def latest_trade_dates(
        self,
        dataset: str = "stock_daily_bar",
        market: str | None = None,
        n: int = 1,
        date_column: str | None = None,
    ) -> list[date]:
        """返回数据集中最近 N 个交易日或月度期间起始日。"""
        files = self._parquet_files(dataset=dataset, market=market)
        symbol = StorageCompat.dataset_symbol_filter(dataset, self.data_source)
        return _scan_latest_trade_dates(files, n, symbol=symbol, date_column=date_column)

    def latest_refresh_dates(
        self,
        dataset: str,
        market: str | None = None,
        n: int = 1,
        symbols: list[str] | None = None,
    ) -> list[date]:
        """返回数据集最近刷新日期，旧快照缺少 updated_at 时回退文件 mtime。"""
        files = self._parquet_files(dataset=dataset, market=market)
        fixed_symbol = StorageCompat.dataset_symbol_filter(dataset, self.data_source)
        effective_symbols = [fixed_symbol] if fixed_symbol else symbols
        return _scan_latest_refresh_dates(files, n, symbols=effective_symbols)

    def get_latest_trade_date(
        self,
        dataset: str,
        market: str | None = None,
        data_source: str | None = None,
    ) -> date | None:
        """返回指定数据集的全表最新落盘交易日。"""
        source = data_source or self.data_source
        catalog: CatalogReadMixin
        if source == self.data_source:
            catalog = self
        else:
            from stock_data.catalog.service import DataCatalog

            catalog = DataCatalog(source, self.storage_dir)
        try:
            from stock_data.core.task_registry import resolve_task

            date_columns = resolve_task(source, dataset).date_columns
            date_column = date_columns[0] if date_columns else None
        except Exception:
            date_column = None
        dates = catalog.latest_trade_dates(
            dataset=dataset,
            market=market,
            n=1,
            date_column=date_column,
        )
        return dates[0] if dates else None

    def list_datasets(self, data_source: str | None = None, market: str | None = None) -> list[str]:
        """返回指定数据源下已落盘的数据集名称列表。"""
        source = data_source or self.data_source
        catalog: CatalogReadMixin = self
        if source == "all":
            all_names: set[str] = set()
            for source_dir in self.storage_dir.iterdir():
                if source_dir.is_dir() and not source_dir.name.startswith("."):
                    from stock_data.catalog.service import DataCatalog

                    catalog = DataCatalog(source_dir.name, self.storage_dir)
                    all_names.update(
                        dataset.dataset for dataset in catalog.available_datasets(market=market)
                    )
            return sorted(all_names)
        if source != self.data_source:
            from stock_data.catalog.service import DataCatalog

            catalog = DataCatalog(source, self.storage_dir)
        return [dataset.dataset for dataset in catalog.available_datasets(market=market)]

    def summary(self, data_source: str | None = None, market: str | None = None) -> pl.DataFrame:
        """一键生成全库或指定数据源的落盘数据资产全景状态表格。"""
        return _build_catalog_summary(self, data_source, market)

    def describe(self, market: str | None = None) -> pl.DataFrame:
        return _build_catalog_description(self, market)
