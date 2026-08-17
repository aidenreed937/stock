"""通用 Feature 长表存储。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from stock.analytics.features.store_ops import merge_incremental
from stock.data.storage.compat import StorageCompat
from stock.utils.logger import logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date


_FEATURE_VALUE_KEYS = (
    "feature_id",
    "entity_type",
    "entity_id",
    "observation_date",
    "definition_version",
)

FEATURE_VALUE_SCHEMA = {
    "feature_id": pl.Utf8,
    "kind": pl.Utf8,
    "entity_type": pl.Utf8,
    "entity_id": pl.Utf8,
    "frequency": pl.Utf8,
    "observation_date": pl.Date,
    "available_at": pl.Utf8,
    "unit": pl.Utf8,
    "value_float": pl.Float64,
    "value_str": pl.Utf8,
    "sample_size": pl.Int64,
    "status": pl.Utf8,
    "definition_version": pl.Utf8,
    "source_watermark": pl.Utf8,
    "input_fingerprint": pl.Utf8,
}


class FeatureValueStore:
    """按定义版本保存和查询通用 Feature 长表。"""

    def __init__(self, mart_dir: Path | str) -> None:
        """初始化长表存储目录。"""
        self.mart_dir = Path(mart_dir)
        self.mart_dir.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """返回通用 Feature 长表路径。"""
        return self.mart_dir / "feature_values.parquet"

    def get(
        self,
        *,
        feature_ids: Sequence[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        definition_version: str | None = None,
    ) -> pl.DataFrame:
        """读取长表并按特征、版本和观察日期过滤。"""
        if not self.path.exists():
            return pl.DataFrame(schema=FEATURE_VALUE_SCHEMA)
        try:
            df = pl.read_parquet(self.path)
        except Exception as exc:
            logger.error(f"FeatureValueStore 读取失败: {exc}")
            return pl.DataFrame(schema=FEATURE_VALUE_SCHEMA)

        df = StorageCompat.safe_cast_date_col(df, "observation_date")
        if start_date is not None:
            df = df.filter(pl.col("observation_date") >= start_date)
        if end_date is not None:
            df = df.filter(pl.col("observation_date") <= end_date)
        if feature_ids:
            df = df.filter(pl.col("feature_id").is_in(feature_ids))
        if definition_version is not None:
            df = df.filter(pl.col("definition_version") == definition_version)
        return df.sort(["observation_date", "feature_id", "definition_version"])

    def save(self, df: pl.DataFrame, *, purge_outside: tuple[date, date] | None = None) -> None:
        """原子持久化长表，同键行保留两侧各自已有的非空字段。

        Args:
            df: 符合 FEATURE_VALUE_SCHEMA 的长表增量。
            purge_outside: 全量重建时同步宽表日期域，删除观察日期落在
                [start, end] 之外的存量行（仅对已存在文件生效）。
        """
        if df.is_empty():
            return
        missing = [column for column in FEATURE_VALUE_SCHEMA if column not in df.columns]
        if missing:
            raise ValueError(f"feature_values 缺少必填列: {', '.join(missing)}")

        save_df = df.select(list(FEATURE_VALUE_SCHEMA)).cast(
            pl.Schema(FEATURE_VALUE_SCHEMA), strict=False
        )
        save_df = StorageCompat.safe_cast_date_col(save_df, "observation_date")
        if self.path.exists():
            existing = pl.read_parquet(self.path)
            existing = StorageCompat.safe_cast_date_col(existing, "observation_date")
            if purge_outside is not None:
                start, end = purge_outside
                existing = existing.filter(
                    (pl.col("observation_date") >= start) & (pl.col("observation_date") <= end)
                )
            save_df = merge_incremental(existing, save_df, keys=_FEATURE_VALUE_KEYS)
        self._write_atomic(save_df.sort(["observation_date", "feature_id", "definition_version"]))

    def _write_atomic(self, df: pl.DataFrame) -> None:
        with tempfile.NamedTemporaryFile(
            dir=self.mart_dir,
            prefix="feature_values_",
            suffix=".tmp.parquet",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            df.write_parquet(tmp_path)
            tmp_path.replace(self.path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
