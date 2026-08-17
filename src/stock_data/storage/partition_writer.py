"""Parquet 分区原子写入与多月份拆分写入器 (ParquetPartitionWriter)。"""

from __future__ import annotations

import threading
from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_core.constants import BAR_DATASETS, SYSTEM_METADATA_COLUMNS
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger
from stock_data.cleaner.date_utils import parse_mixed_date
from stock_data.storage.compat import StorageCompat
from stock_data.task_registry import is_task_partitioned

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


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


def _append_write_buffer(
    lock: Any,
    write_buffer: dict[Path, list[Any]],
    file_path: Path,
    item: Any,
) -> None:
    """在共享文件锁下追加 batch 缓冲项。"""
    with lock:
        write_buffer.setdefault(file_path, []).append(item)


def validate_frame_source(df: pl.DataFrame, data_source: str, context: str) -> None:
    if "data_source" not in df.columns:
        raise DataValidationError(f"{context}缺少 data_source 血统字段")
    sources = set(df.get_column("data_source").drop_nulls().unique().to_list())
    if not sources:
        raise DataValidationError(f"{context}中 data_source 字段全为空")
    if any(s != data_source for s in sources):
        raise DataValidationError(
            f"{context}数据源不匹配: 期望 [{data_source}]，实际包含 {sorted(sources)}"
        )


def validate_schema_version(df: pl.DataFrame, context: str) -> None:
    if "schema_version" not in df.columns or df.is_empty():
        return
    versions = {
        str(v)
        for v in df.get_column("schema_version")
        .cast(pl.Utf8, strict=False)
        .drop_nulls()
        .unique()
        .to_list()
        if str(v)
    }
    invalid = versions - {"v2"}
    if invalid:
        raise DataValidationError(f"{context}包含旧版或未知 schema_version: {sorted(invalid)}")


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


class ParquetPartitionWriter:
    """处理 Parquet 文件的多月份数据动态拆分、内存攒批与并发文件锁原子合并落盘。"""

    _BAR_DATASETS = BAR_DATASETS

    def __init__(self, data_source: str | None = None) -> None:
        """初始化 Parquet 分区写入器。"""
        self.data_source = data_source
        self._batch_mode = False
        self._write_buffer: dict[Path, list[tuple[pl.DataFrame, str]]] = {}
        self._file_lock = threading.Lock()

    def enable_batch_mode(self) -> None:
        """启用内存攒批模式。"""
        self._batch_mode = True
        self._write_buffer = {}
        logger.info("ParquetPartitionWriter 已开启攒批写入模式 (Micro-batching)")

    def commit(self, cache_updater: Callable[[Path, pl.DataFrame], None] | None = None) -> None:
        """提交 batch 缓冲区中的所有分区数据。"""
        if not self._batch_mode or not self._write_buffer:
            self._batch_mode = False
            return

        logger.info(f"开始提交攒批数据，共涉及 {len(self._write_buffer)} 个目标文件分区...")
        for file_path, items in self._write_buffer.items():
            if not items:
                continue
            sources = {source for _, source in items}
            if len(sources) != 1:
                raise DataValidationError(
                    f"Curated 攒批目标 [{file_path}] 混入多个数据源: {sorted(sources)}"
                )
            source = next(iter(sources))
            merged = self.merge_and_save_parquet(file_path, [df for df, _ in items], source=source)
            if cache_updater is not None:
                cache_updater(file_path, merged)
            logger.info(f"攒批合并落盘成功 -> {file_path} (合并后共 {len(merged)} 行)")

        self._write_buffer.clear()
        self._batch_mode = False
        logger.info("攒批提交完成，已自动关闭攒批模式。")

    def merge_and_save_parquet(
        self, file_path: Path, dfs: list[pl.DataFrame], source: str | None = None
    ) -> pl.DataFrame:
        """读取现有文件、合并新数据帧列表、去重与时序排序，并原子写回 Parquet。"""
        with self._file_lock:
            dataset_name = (
                file_path.parent.parent.parent.name
                if file_path.parent.name.startswith("month=")
                else file_path.parent.name
            )
            existing = pl.read_parquet(file_path) if file_path.exists() else pl.DataFrame()
            if not existing.is_empty():
                existing = StorageCompat.normalize_identity_columns(existing)
                existing = StorageCompat.post_process_dataset(dataset_name, existing)
                validate_schema_version(existing, f"已有 Curated 文件 [{file_path}]")
            normalized_dfs = [
                StorageCompat.post_process_dataset(
                    dataset_name, StorageCompat.normalize_identity_columns(df)
                )
                for df in dfs
            ]
            for df in normalized_dfs:
                validate_schema_version(df, f"Curated 新数据 [{file_path}]")

            existing, normalized_dfs = _align_optional_bar_columns(
                existing, normalized_dfs, dataset_name
            )
            existing, normalized_dfs = _align_optional_index_fundamental_columns(
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
                dataset_name, source, self.data_source, merged, bar_datasets=self._BAR_DATASETS
            )
            if dedup_cols:
                merged = merged.unique(subset=dedup_cols, keep="last")
            merged = StorageCompat.post_process_dataset(dataset_name, merged)

            sort_cols = [c for c in ["trade_date", "symbol"] if c in merged.columns]
            if sort_cols:
                merged = merged.sort(sort_cols)

            file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = file_path.with_suffix(".tmp.parquet")
            merged.write_parquet(temp_path)
            temp_path.replace(file_path)

        return merged

    def save_partitioned(
        self,
        df: pl.DataFrame,
        dataset_name: str,
        fallback_date: date,
        market_code: str,
        source: str,
        storage_dir: Path,
        path_resolver: Callable[[str, date, str], Path],
        cache_updater: Callable[[Path, pl.DataFrame], None] | None = None,
    ) -> Path:
        """根据数据集属性决定单表落盘或动态按交易日年月拆分落盘。"""
        if not is_task_partitioned(source, dataset_name):
            file_path = (
                storage_dir / f"market={market_code.upper()}" / dataset_name / "data.parquet"
            )
            self._save_single(file_path, df, dataset_name, source, cache_updater)
            return file_path

        date_col = next(
            (
                c
                for c in ["trade_date", "date", "end_date", "as_of_date", "Date"]
                if c in df.columns
            ),
            None,
        )
        if not date_col or df.is_empty():
            file_path = path_resolver(dataset_name, fallback_date, market_code)
            self._save_single(file_path, df, dataset_name, source, cache_updater)
            return file_path

        try:
            parsed = df.with_columns(parse_mixed_date(date_col).alias("_dt"))
            valid = parsed.filter(pl.col("_dt").is_not_null())
            invalid_count = len(parsed) - len(valid)
            if invalid_count:
                raise DataValidationError(
                    f"Curated 数据集 [{dataset_name}] 日期列 [{date_col}] "
                    f"包含 {invalid_count} 条无法解析的日期"
                )
            if valid.is_empty():
                file_path = path_resolver(dataset_name, fallback_date, market_code)
                self._save_single(file_path, df, dataset_name, source, cache_updater)
                return file_path

            grouped = valid.with_columns(
                [
                    pl.col("_dt").dt.year().alias("_y"),
                    pl.col("_dt").dt.month().alias("_m"),
                ]
            )
            last_path = None
            for (yr, mo), sub_df in grouped.partition_by(["_y", "_m"], as_dict=True).items():
                if yr is None or mo is None:
                    continue
                clean_sub = sub_df.drop(["_dt", "_y", "_m"])
                sub_path = path_resolver(dataset_name, date(int(yr), int(mo), 1), market_code)
                self._save_single(sub_path, clean_sub, dataset_name, source, cache_updater)
                last_path = sub_path

            return last_path or path_resolver(dataset_name, fallback_date, market_code)
        except DataValidationError:
            raise
        except Exception as e:
            logger.warning(f"动态按交易日拆分落盘异常，降级使用统一时间分区: {e}")
            file_path = path_resolver(dataset_name, fallback_date, market_code)
            self._save_single(file_path, df, dataset_name, source, cache_updater)
            return file_path

    def _save_single(
        self,
        file_path: Path,
        df: pl.DataFrame,
        dataset_name: str,
        source: str,
        cache_updater: Callable[[Path, pl.DataFrame], None] | None = None,
    ) -> None:
        if self._batch_mode:
            _append_write_buffer(self._file_lock, self._write_buffer, file_path, (df, source))
            logger.debug(f"已加入攒批写入缓存 [{dataset_name}] -> {file_path}")
        else:
            merged = self.merge_and_save_parquet(file_path, [df], source=source)
            if cache_updater is not None:
                cache_updater(file_path, merged)
            logger.info(f"精炼数据落盘成功 [{dataset_name}] -> {file_path} ({len(merged)} 行)")
