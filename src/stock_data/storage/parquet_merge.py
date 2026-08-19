"""Curated Parquet 文件合并、schema 对齐与原子替换引擎。"""

from __future__ import annotations

import fcntl
import threading
import uuid
from os import O_CREAT, O_RDWR
from os import open as os_open
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.constants import BAR_DATASETS, SYSTEM_METADATA_COLUMNS
from stock_core.exceptions import DataValidationError
from stock_data.storage.compat import StorageCompat
from stock_data.storage.read_compat import validate_schema_version

_OPTIONAL_BAR_COLUMNS = frozenset({"backwardComplexFactor", "complexFactor"})
_OPTIONAL_INDEX_FUNDAMENTAL_COLUMNS = frozenset(
    {
        "pe_ttm.ew",
        "pe_ttm.mcw",
        "pb.ew",
        "pb.mcw",
        "ps_ttm.ew",
        "ps_ttm.mcw",
        "dyr.ew",
        "dyr.mcw",
        "mc",
    }
)
_YFINANCE_FINANCIAL_DATASETS = frozenset({"financials", "balance_sheet", "cashflow"})

_FILE_LOCKS_GUARD = threading.Lock()
_FILE_LOCKS: dict[Path, threading.Lock] = {}


class _CrossProcessFileLock:
    """同时覆盖线程与进程的目标文件锁。"""

    def __init__(self, file_path: Path, thread_lock: threading.Lock) -> None:
        self.file_path = file_path.resolve()
        self.thread_lock = thread_lock
        self._fd: int | None = None

    def __enter__(self) -> _CrossProcessFileLock:
        self.thread_lock.acquire()
        try:
            lock_path = self.file_path.with_name(f".{self.file_path.name}.lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os_open(lock_path, O_CREAT | O_RDWR, 0o600)
            fcntl.flock(self._fd, fcntl.LOCK_EX)
        except Exception:
            self.thread_lock.release()
            raise
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            import os

            os.close(self._fd)
            self._fd = None
        self.thread_lock.release()


def _shared_file_lock(file_path: Path) -> _CrossProcessFileLock:
    """返回按目标文件复用且跨进程生效的排他写锁。"""
    resolved_path = file_path.resolve()
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(resolved_path)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[resolved_path] = lock
    return _CrossProcessFileLock(resolved_path, lock)


def validate_frame_source(df: pl.DataFrame, data_source: str, context: str) -> None:
    if "data_source" not in df.columns:
        raise DataValidationError(f"{context}缺少 data_source 血统字段")
    sources = set(df.get_column("data_source").drop_nulls().unique().to_list())
    if not sources:
        raise DataValidationError(f"{context}中 data_source 字段全为空")
    if any(source != data_source for source in sources):
        raise DataValidationError(
            f"{context}数据源不匹配: 期望 [{data_source}]，实际包含 {sorted(sources)}"
        )


def _align_optional_bar_columns(
    existing: pl.DataFrame, incoming: list[pl.DataFrame], dataset_name: str
) -> tuple[pl.DataFrame, list[pl.DataFrame]]:
    """兼容行情源端可选字段增删，同时保留未知字段变更的严格校验。"""
    if dataset_name not in BAR_DATASETS or existing.is_empty() or not incoming:
        return existing, incoming

    existing_columns = set(existing.columns)
    incoming_columns = set().union(*(set(frame.columns) for frame in incoming))
    optional_columns = (existing_columns | incoming_columns) & _OPTIONAL_BAR_COLUMNS
    for column in optional_columns:
        if column not in existing_columns:
            dtype = next(frame.schema[column] for frame in incoming if column in frame.columns)
            existing = existing.with_columns(pl.lit(None, dtype=dtype).alias(column))
        incoming = [
            frame
            if column in frame.columns
            else frame.with_columns(pl.lit(None, dtype=existing.schema[column]).alias(column))
            for frame in incoming
        ]
    return existing, incoming


def _align_optional_index_fundamental_columns(
    existing: pl.DataFrame, incoming: list[pl.DataFrame], dataset_name: str
) -> tuple[pl.DataFrame, list[pl.DataFrame]]:
    """兼容指数估值新增已知指标列，同时保留未知字段变更的严格校验。"""
    if dataset_name != "index_fundamental" or existing.is_empty() or not incoming:
        return existing, incoming

    existing_columns = set(existing.columns)
    incoming_columns = set().union(*(set(frame.columns) for frame in incoming))
    optional_columns = (existing_columns | incoming_columns) & _OPTIONAL_INDEX_FUNDAMENTAL_COLUMNS
    for column in optional_columns:
        if column not in existing_columns:
            dtype = next(frame.schema[column] for frame in incoming if column in frame.columns)
            existing = existing.with_columns(pl.lit(None, dtype=dtype).alias(column))
        incoming = [
            frame
            if column in frame.columns
            else frame.with_columns(pl.lit(None, dtype=existing.schema[column]).alias(column))
            for frame in incoming
        ]
    return existing, incoming


def _align_financial_statement_columns(
    existing: pl.DataFrame, incoming: list[pl.DataFrame], dataset_name: str
) -> tuple[pl.DataFrame, list[pl.DataFrame]]:
    """按财报字段并集对齐列，允许 Yahoo 新增或缺少财务科目。"""
    if dataset_name not in _YFINANCE_FINANCIAL_DATASETS or existing.is_empty() or not incoming:
        return existing, incoming

    columns = list(existing.columns)
    for frame in incoming:
        columns.extend(column for column in frame.columns if column not in columns)
    for column in columns:
        if column not in existing.columns:
            dtype = next(frame.schema[column] for frame in incoming if column in frame.columns)
            existing = existing.with_columns(pl.lit(None, dtype=dtype).alias(column))
        dtype = existing.schema[column]
        incoming = [
            frame
            if column in frame.columns
            else frame.with_columns(pl.lit(None, dtype=dtype).alias(column))
            for frame in incoming
        ]
    return existing, incoming


def merge_and_save_parquet(
    file_path: Path,
    dfs: list[pl.DataFrame],
    source: str | None,
    data_source: str | None,
    bar_datasets: tuple[str, ...] | frozenset[str] | set[str],
) -> pl.DataFrame:
    """读取现有文件、合并新数据、去重并原子写回 Parquet。"""
    with _shared_file_lock(file_path):
        dataset_name = (
            file_path.parent.parent.parent.name
            if file_path.parent.name.startswith("month=")
            else file_path.parent.name
        )
        existing = pl.read_parquet(file_path) if file_path.exists() else pl.DataFrame()
        if not existing.is_empty():
            existing = StorageCompat.post_process_dataset(
                dataset_name, StorageCompat.normalize_identity_columns(existing)
            )
            validate_schema_version(existing, f"已有 Curated 文件 [{file_path}]")
        normalized_dfs = [
            StorageCompat.post_process_dataset(
                dataset_name, StorageCompat.normalize_identity_columns(df)
            )
            for df in dfs
        ]
        reference_frames = [existing, *normalized_dfs]
        existing = StorageCompat.normalize_nested_columns(
            existing, reference_frames=reference_frames
        )
        normalized_dfs = [
            StorageCompat.normalize_nested_columns(df, reference_frames=reference_frames)
            for df in normalized_dfs
        ]
        for df in normalized_dfs:
            validate_schema_version(df, f"Curated 新数据 [{file_path}]")

        existing, normalized_dfs = _align_optional_bar_columns(
            existing, normalized_dfs, dataset_name
        )
        existing, normalized_dfs = _align_optional_index_fundamental_columns(
            existing, normalized_dfs, dataset_name
        )
        existing, normalized_dfs = _align_financial_statement_columns(
            existing, normalized_dfs, dataset_name
        )

        if not existing.is_empty() and source is not None:
            validate_frame_source(existing, source, f"已有 Curated 文件 [{file_path}]")
            for df in normalized_dfs:
                if (set(df.columns) - SYSTEM_METADATA_COLUMNS) != (
                    set(existing.columns) - SYSTEM_METADATA_COLUMNS
                ):
                    raise DataValidationError(
                        f"Curated 文件 [{file_path}] schema 不匹配: "
                        f"已有列 {sorted(existing.columns)}，新数据列 {sorted(df.columns)}"
                    )

        all_dfs = [existing, *normalized_dfs] if not existing.is_empty() else normalized_dfs
        all_dfs = [StorageCompat.normalize_datetime_columns(df) for df in all_dfs]
        merged = pl.concat(all_dfs, how="diagonal_relaxed")
        dedup_cols = StorageCompat.resolve_dedup_keys(
            dataset_name, source, data_source, merged, bar_datasets=bar_datasets
        )
        if dedup_cols:
            merged = merged.unique(subset=dedup_cols, keep="last")
        merged = StorageCompat.post_process_dataset(dataset_name, merged)
        sort_cols = [
            column for column in ("trade_date", "as_of_date", "symbol") if column in merged.columns
        ]
        if sort_cols:
            merged = merged.sort(sort_cols)

        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = file_path.with_name(f"{file_path.stem}.{uuid.uuid4().hex}.tmp.parquet")
        try:
            merged.write_parquet(temp_path)
            temp_path.replace(file_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    return merged
