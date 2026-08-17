"""统一读取本地已落盘 Curated Parquet 数据的数据目录服务 (DataCatalog)。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

import polars as pl

from stock.config.settings import settings
from stock.data.catalog_ops import (
    build_catalog_summary as _build_catalog_summary,
    dataset_name as _dataset_name,
    list_parquet_files as _list_parquet_files,
    normalize_identity_columns as _normalize_identity_columns,
    path_intersects_range as _path_intersects_range,
    read_dataset_files as _read_dataset_files,
    resolve_dataset_alias as _resolve_dataset_alias,
    scan_latest_trade_dates as _scan_latest_trade_dates,
    validate_bars as _validate_bars,
    validate_schema_version as _validate_schema_version,
)
from stock.data.storage.compat import StorageCompat
from stock.utils.logger import logger

_ARTIFACT_SUFFIXES = (".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet")


def load_dataset_compat(
    catalog: Any,
    dataset: str,
    *,
    columns: Sequence[str] | None = None,
    **kwargs: Any,
) -> pl.DataFrame:
    """按加载器签名传递可用参数，并在需要时执行列投影。"""
    loader = catalog.load_dataset
    parameters: Mapping[str, Parameter]
    try:
        parameters = signature(loader).parameters
    except (TypeError, ValueError):
        parameters = {}
    accepts_kwargs = any(
        parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    call_kwargs = {
        key: value
        for key, value in kwargs.items()
        if (key in parameters or accepts_kwargs) and value is not None
    }
    if columns is not None and ("columns" in parameters or accepts_kwargs):
        call_kwargs["columns"] = columns

    frame = loader(dataset, **call_kwargs)
    if not isinstance(frame, pl.DataFrame):
        return pl.DataFrame()
    if columns is not None and not frame.is_empty():
        return frame.select([column for column in columns if column in frame.columns])
    return frame


@dataclass(frozen=True)
class CatalogDataset:
    """数据目录中一个数据集的定位信息。"""

    data_source: str
    dataset: str
    files: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def total_rows(self) -> int | None:
        if not self.files:
            return None
        try:
            return int(
                sum(pl.scan_parquet(path).select(pl.len()).collect().item() for path in self.files)
            )
        except Exception:
            return None


class DataCatalog:
    """按数据源隔离的本地落盘数据统一读取入口。"""

    def __init__(
        self,
        data_source: str | None = None,
        storage_dir: Path | str | None = None,
    ) -> None:
        self.data_source = data_source or settings.data_source_mode
        self.storage_dir = (
            Path(storage_dir) if storage_dir is not None else settings.curated_data_dir
        )
        if not self.storage_dir.exists():
            raise FileNotFoundError(f"Curated 数据目录不存在: {self.storage_dir}")

    def _parquet_files(self, dataset: str | None = None, market: str | None = None) -> list[Path]:
        return _list_parquet_files(
            self.storage_dir / self.data_source, dataset=dataset, market=market
        )

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
        """读取标准数据集（非行情类也可用），可按标的与日期范围过滤，支持列投影。"""
        resolved = _resolve_dataset_alias(self.data_source, dataset)
        files = _list_parquet_files(
            self.storage_dir / self.data_source, dataset=resolved, market=market
        )
        df = _read_dataset_files(
            files,
            resolved,
            self.data_source,
            start_date,
            end_date,
            symbols,
            columns=columns,
        )
        if dedup and (
            k := StorageCompat.resolve_dedup_keys(resolved, self.data_source, self.data_source, df)
        ):
            if all(col in df.columns for col in k):
                df = df.unique(subset=k, keep="last")
        if columns is not None and not df.is_empty():
            selected = [c for c in columns if c in df.columns]
            df = df.select(selected)
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
        """读取行情（K 线）数据并进行时序排序与有效性校验，支持列投影。"""
        resolved = _resolve_dataset_alias(self.data_source, dataset)
        if symbol is not None:
            symbols = [symbol]
        files = _list_parquet_files(
            self.storage_dir / self.data_source, dataset=resolved, market=market
        )
        df = _read_dataset_files(
            files,
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
            dedup_cols = [c for c in ("market", "symbol", "trade_date") if c in df.columns]
            if dedup_cols:
                df = df.unique(subset=dedup_cols, keep="last")
        if "trade_date" in df.columns:
            sort_cols = [c for c in ("trade_date", "symbol") if c in df.columns]
            df = df.sort(sort_cols)

        if validate:
            _validate_bars(df, resolved)

        if columns is not None and not df.is_empty():
            selected = [c for c in columns if c in df.columns]
            df = df.select(selected)
        return df

    def latest_trade_dates(
        self,
        dataset: str = "stock_daily_bar",
        market: str | None = None,
        n: int = 1,
    ) -> list[date]:
        """返回数据集中最近 N 个交易日或月度期间起始日（降序）。"""
        resolved = _resolve_dataset_alias(self.data_source, dataset)
        files = _list_parquet_files(
            self.storage_dir / self.data_source, dataset=resolved, market=market
        )
        return _scan_latest_trade_dates(files, n)

    def get_latest_trade_date(
        self,
        dataset: str,
        market: str | None = None,
        data_source: str | None = None,
    ) -> date | None:
        """返回指定数据集的全表最新落盘交易日（标量 date）。"""
        ds = data_source or self.data_source
        cat = (
            self
            if ds == self.data_source
            else DataCatalog(data_source=ds, storage_dir=self.storage_dir)
        )
        dates = cat.latest_trade_dates(dataset=dataset, market=market, n=1)
        return dates[0] if dates else None

    def list_datasets(self, data_source: str | None = None, market: str | None = None) -> list[str]:
        """返回指定数据源（或当前数据源，传入 'all' 时扫描全库）下已落盘的数据集名称列表。"""
        ds = data_source or self.data_source
        if ds == "all":
            all_names: set[str] = set()
            for source_dir in self.storage_dir.iterdir():
                if source_dir.is_dir() and not source_dir.name.startswith("."):
                    cat = DataCatalog(data_source=source_dir.name, storage_dir=self.storage_dir)
                    all_names.update(d.dataset for d in cat.available_datasets(market=market))
            return sorted(all_names)
        cat = (
            self
            if ds == self.data_source
            else DataCatalog(data_source=ds, storage_dir=self.storage_dir)
        )
        return [d.dataset for d in cat.available_datasets(market=market)]

    def summary(self, data_source: str | None = None, market: str | None = None) -> pl.DataFrame:
        """一键生成全库或指定数据源的落盘数据资产全景状态表格。"""
        return _build_catalog_summary(self, data_source, market)

    def describe(self, market: str | None = None) -> pl.DataFrame:
        """生成数据目录摘要（数据集、文件数、总行数）。"""
        rows = [
            {
                "data_source": self.data_source,
                "dataset": entry.dataset,
                "files": len(entry.files),
                "rows": entry.total_rows,
            }
            for entry in self.available_datasets(market=market)
        ]
        return (
            pl.DataFrame(rows)
            if rows
            else pl.DataFrame(
                schema={
                    "data_source": pl.Utf8,
                    "dataset": pl.Utf8,
                    "files": pl.Int64,
                    "rows": pl.Int64,
                }
            )
        )
