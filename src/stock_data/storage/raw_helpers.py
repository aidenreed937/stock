"""RAW 原始数据存储辅助函数模块。"""

from __future__ import annotations

import threading
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.contracts import DatasetKey
from stock_data.storage.raw_schema import (
    RAW_DATE_COLUMNS,
    first_existing_column,
    month_key_for,
)

_FILE_LOCKS_GUARD = threading.Lock()
_FILE_LOCKS: dict[Path, threading.Lock] = {}


def shared_file_lock(file_path: Path) -> threading.Lock:
    """返回当前进程内按目标文件复用的读写锁。"""
    resolved_path = file_path.resolve()
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(resolved_path)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[resolved_path] = lock
        return lock


def append_write_buffer(
    lock: Any,
    write_buffer: dict[Path, list[Any]],
    file_path: Path,
    item: Any,
) -> None:
    """在共享文件锁下追加 batch 缓冲项。"""
    with lock:
        write_buffer.setdefault(file_path, []).append(item)


def iter_month_starts(start_date: date, end_date: date) -> list[date]:
    months: list[date] = []
    current = date(start_date.year, start_date.month, 1)
    last = date(end_date.year, end_date.month, 1)
    while current <= last:
        months.append(current)
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return months


def dataset_paths_for_key(storage: Any, key: DatasetKey) -> list[Path]:
    paths: list[Path] = []
    for month_start in iter_month_starts(key.start_date, key.end_date):
        path = storage._get_dataset_path(month_key_for(key, month_start))
        if path not in paths:
            paths.append(path)
    return paths


def date_column_for_key(key: DatasetKey, df: pl.DataFrame) -> str | None:
    """按任务契约选择 RAW 的业务日期列，优先使用报告期而非公告日。"""
    try:
        from stock_data.core.task_registry import resolve_task

        task = resolve_task(key.provider, key.endpoint)
        candidates = (*task.date_columns, *RAW_DATE_COLUMNS)
    except Exception:
        candidates = RAW_DATE_COLUMNS
    return first_existing_column(df, tuple(dict.fromkeys(candidates)))


def read_dataset_paths(paths: list[Path]) -> pl.DataFrame | None:
    with ExitStack() as stack:
        for path in sorted(paths, key=str):
            stack.enter_context(shared_file_lock(path))
        if any(not path.exists() for path in paths):
            return None
        frames = [pl.read_parquet(path) for path in paths]
    frames = [frame for frame in frames if not frame.is_empty()]
    if not frames:
        return None
    return frames[0] if len(frames) == 1 else pl.concat(frames, how="diagonal_relaxed")


def is_event_frequency_task(provider: str, endpoint: str) -> bool:
    """检查是否为事件级（非日历连续）任务。"""
    try:
        from stock_data.core.task_registry import resolve_task

        task = resolve_task(provider, endpoint)
        return task.frequency == "event"
    except Exception:
        return False
