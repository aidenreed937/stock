"""Parquet 分区原子写入与多月份拆分写入器 (ParquetPartitionWriter)。"""

from datetime import date
from pathlib import Path
import threading
from typing import Callable
import polars as pl

from stock.constants import BAR_DATASETS
from stock.data.storage.compat import StorageCompat
from stock.data.task_registry import is_task_partitioned
from stock.exceptions import DataValidationError
from stock.utils.date import parse_mixed_date
from stock.utils.logger import logger


class ParquetPartitionWriter:
    """处理 Parquet 文件的多月份数据动态拆分、内存攒批与并发文件锁原子合并落盘。"""

    _BAR_DATASETS = BAR_DATASETS

    def __init__(self, data_source: str | None = None) -> None:
        self.data_source = data_source
        self._batch_mode = False
        self._write_buffer: dict[Path, list[pl.DataFrame]] = {}
        self._file_lock = threading.Lock()

    def enable_batch_mode(self) -> None:
        self._batch_mode = True
        self._write_buffer = {}
        logger.info("ParquetPartitionWriter 已开启攒批写入模式 (Micro-batching)")

    def commit(self, cache_updater: Callable[[Path, pl.DataFrame], None] | None = None) -> None:
        if not getattr(self, "_batch_mode", False) or not getattr(self, "_write_buffer", {}):
            self._batch_mode = False
            return

        logger.info(f"开始提交攒批数据，共涉及 {len(self._write_buffer)} 个目标文件分区...")
        for file_path, dfs in self._write_buffer.items():
            if not dfs:
                continue
            merged = self.merge_and_save_parquet(file_path, dfs)
            if cache_updater is not None:
                cache_updater(file_path, merged)
            logger.info(f"攒批合并落盘成功 -> {file_path} (合并后共 {len(merged)} 行)")

        self._write_buffer.clear()
        self._batch_mode = False
        logger.info("攒批提交完成，已自动关闭攒批模式。")

    def merge_and_save_parquet(
        self, file_path: Path, dfs: list[pl.DataFrame], source: str | None = None
    ) -> pl.DataFrame:
        """读取现有文件、合并新数据帧列表、进行去重与排序，并原子写入 Parquet。"""
        with self._file_lock:
            dataset_name = file_path.parent.name
            if dataset_name.startswith("month="):
                dataset_name = file_path.parent.parent.parent.name
            existing = pl.read_parquet(file_path) if file_path.exists() else pl.DataFrame()
            if not existing.is_empty():
                existing = StorageCompat.normalize_identity_columns(existing)
            normalized_dfs = [StorageCompat.normalize_identity_columns(df) for df in dfs]
            if not existing.is_empty() and source is not None:
                self._validate_frame_source(existing, source, f"已有 Curated 文件 [{file_path}]")
                for df in normalized_dfs:
                    if set(df.columns) != set(existing.columns):
                        raise DataValidationError(
                            f"Curated 文件 [{file_path}] schema 不匹配: "
                            f"已有列 {sorted(existing.columns)}，新数据列 {sorted(df.columns)}"
                        )

            all_dfs = ([existing] + normalized_dfs) if not existing.is_empty() else normalized_dfs
            all_dfs = [StorageCompat.normalize_datetime_columns(df) for df in all_dfs]
            merged = pl.concat(all_dfs, how="diagonal_relaxed")

            dedup_cols = StorageCompat.resolve_dedup_keys(
                dataset_name, source, self.data_source, merged, bar_datasets=self._BAR_DATASETS
            )
            if dedup_cols:
                merged = merged.unique(subset=dedup_cols, keep="last")
            if dataset_name == "hk_hold" and "symbol" in merged.columns:
                qualified_symbols = merged.filter(
                    pl.col("symbol").cast(pl.Utf8, strict=False).str.contains(r"\.")
                )
                if not qualified_symbols.is_empty():
                    merged = merged.filter(
                        pl.col("symbol").cast(pl.Utf8, strict=False).str.contains(r"\.")
                    )
            if "trade_date" in merged.columns and "symbol" in merged.columns:
                merged = merged.sort(["trade_date", "symbol"])

            file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = file_path.with_suffix(".tmp.parquet")
            merged.write_parquet(temp_path)
            temp_path.replace(file_path)

        return merged

    def _validate_frame_source(self, df: pl.DataFrame, data_source: str, context: str) -> None:
        if "data_source" not in df.columns:
            raise DataValidationError(f"{context}缺少 data_source 血统字段")
        sources = set(df.get_column("data_source").drop_nulls().unique().to_list())
        if not sources:
            raise DataValidationError(f"{context}中 data_source 字段全为空")
        if any(source != data_source for source in sources):
            raise DataValidationError(
                f"{context}数据源不匹配: 期望 [{data_source}]，实际包含 {sorted(sources)}"
            )

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
        if not is_task_partitioned(source, dataset_name):
            file_path = (
                storage_dir / f"market={market_code.upper()}" / dataset_name / "data.parquet"
            )
            self._save_single(file_path, df, dataset_name, source, cache_updater)
            return file_path

        date_col = next(
            (c for c in ["trade_date", "date", "end_date", "as_of_date", "Date"] if c in df.columns),
            None,
        )
        if not date_col or df.is_empty():
            file_path = path_resolver(dataset_name, fallback_date, market_code)
            self._save_single(file_path, df, dataset_name, source, cache_updater)
            return file_path

        try:
            parsed_df = df.with_columns(parse_mixed_date(date_col).alias("_parsed_date"))
            valid_df = parsed_df.filter(pl.col("_parsed_date").is_not_null())
            if valid_df.is_empty():
                file_path = path_resolver(dataset_name, fallback_date, market_code)
                self._save_single(file_path, df, dataset_name, source, cache_updater)
                return file_path

            grouped = valid_df.with_columns(
                [
                    pl.col("_parsed_date").dt.year().alias("_part_year"),
                    pl.col("_parsed_date").dt.month().alias("_part_month"),
                ]
            )
            ym_pairs = grouped.select(["_part_year", "_part_month"]).unique().iter_rows()
            last_path = None
            for yr, mo in ym_pairs:
                if yr is None or mo is None:
                    continue
                sub_df = grouped.filter(
                    (pl.col("_part_year") == yr) & (pl.col("_part_month") == mo)
                ).drop(["_parsed_date", "_part_year", "_part_month"])
                sub_date = date(int(yr), int(mo), 1)
                sub_path = path_resolver(dataset_name, sub_date, market_code)
                self._save_single(sub_path, sub_df, dataset_name, source, cache_updater)
                last_path = sub_path

            return last_path or path_resolver(dataset_name, fallback_date, market_code)
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
        if getattr(self, "_batch_mode", False):
            if file_path not in self._write_buffer:
                self._write_buffer[file_path] = []
            self._write_buffer[file_path].append(df)
            logger.debug(f"已加入攒批写入缓存 [{dataset_name}] -> {file_path}")
        else:
            merged = self.merge_and_save_parquet(file_path, [df], source=source)
            if cache_updater is not None:
                cache_updater(file_path, merged)
            logger.info(f"精炼数据落盘成功 [{dataset_name}] -> {file_path} ({len(merged)} 行)")
