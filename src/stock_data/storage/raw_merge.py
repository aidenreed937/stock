"""RAW 文件合并前的嵌套字段归一与去重。"""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from stock_core.contracts import DatasetKey
from stock_data.storage.compat import StorageCompat
from stock_data.storage.raw_schema import deduplicate_raw_merged_frame


def merge_raw_frames(
    existing: pl.DataFrame,
    items: list[tuple[DatasetKey, pl.DataFrame]],
    replace_existing: bool,
    backup_legacy_file: Callable[[], None],
) -> pl.DataFrame:
    """归一 RAW 嵌套列、合并新旧帧并按注册主键去重。"""
    reference_frames = [existing, *(frame for _, frame in items)]
    existing = StorageCompat.normalize_nested_columns(existing, reference_frames=reference_frames)
    normalized_items = [
        (
            key,
            StorageCompat.normalize_nested_columns(frame, reference_frames=reference_frames),
        )
        for key, frame in items
    ]
    incoming_columns = {column for _, frame in normalized_items for column in frame.columns}
    if (
        replace_existing
        and not existing.is_empty()
        and not incoming_columns.issubset(existing.columns)
    ):
        backup_legacy_file()
        existing = pl.DataFrame()

    frames = [existing] if not existing.is_empty() else []
    frames.extend(frame for _, frame in normalized_items)
    merged = pl.concat(frames, how="diagonal_relaxed")
    return deduplicate_raw_merged_frame(
        merged, normalized_items[0][0] if normalized_items else None
    )
