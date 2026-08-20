"""RAW 原始数据离线时间分区归档存储引擎。"""

import shutil
import threading
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.contracts import DatasetKey
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger
from stock_data.core.runtime import DataRuntimeContext
from stock_data.core.settings import data_settings
from stock_data.governance.quality.margin_coverage import is_margin_complete
from stock_data.pipeline.cleaner.date_utils import parse_mixed_date
from stock_data.storage.compat import StorageCompat
from stock_data.storage.raw_cache import has_raw_cache
from stock_data.storage.raw_merge import merge_raw_frames
from stock_data.storage.raw_schema import (
    RAW_DATE_COLUMNS,
    RAW_RANGE_DATE_COLUMNS,
    RAW_SYMBOL_COLUMNS,
    first_existing_column,
    month_key_for,
    normalize_raw_date_series,
    resolve_raw_primary_keys,
)

_FILE_LOCKS_GUARD = threading.Lock()
_FILE_LOCKS: dict[Path, threading.Lock] = {}


def _shared_file_lock(file_path: Path) -> threading.Lock:
    """返回当前进程内按目标文件复用的读写锁。"""
    resolved_path = file_path.resolve()
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(resolved_path)
        if lock is None:
            lock = threading.Lock()
            _FILE_LOCKS[resolved_path] = lock
        return lock


def _append_write_buffer(
    lock: Any,
    write_buffer: dict[Path, list[Any]],
    file_path: Path,
    item: Any,
) -> None:
    """在共享文件锁下追加 batch 缓冲项。"""
    with lock:
        write_buffer.setdefault(file_path, []).append(item)


def _iter_month_starts(start_date: date, end_date: date) -> list[date]:
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


def _dataset_paths_for_key(storage: Any, key: DatasetKey) -> list[Path]:
    paths: list[Path] = []
    for month_start in _iter_month_starts(key.start_date, key.end_date):
        path = storage._get_dataset_path(month_key_for(key, month_start))
        if path not in paths:
            paths.append(path)
    return paths


def _date_column_for_key(key: DatasetKey, df: pl.DataFrame) -> str | None:
    """按任务契约选择 RAW 的业务日期列，优先使用报告期而非公告日。"""
    try:
        from stock_data.core.task_registry import resolve_task

        task = resolve_task(key.provider, key.endpoint)
        candidates = (*task.date_columns, *RAW_DATE_COLUMNS)
    except Exception:
        candidates = RAW_DATE_COLUMNS
    return first_existing_column(df, tuple(dict.fromkeys(candidates)))


def _read_dataset_paths(paths: list[Path]) -> pl.DataFrame | None:
    with ExitStack() as stack:
        for path in sorted(paths, key=str):
            stack.enter_context(_shared_file_lock(path))
        if any(not path.exists() for path in paths):
            return None
        frames = [pl.read_parquet(path) for path in paths]
    frames = [frame for frame in frames if not frame.is_empty()]
    if not frames:
        return None
    return frames[0] if len(frames) == 1 else pl.concat(frames, how="diagonal_relaxed")


class RawDataStorage:
    """RAW 原始数据存储引擎。

    使用标准的 Hive 风格时间分区归档保存外部 API 原始响应数据:
    路径规范: data/raw/{data_source}/{endpoint}/year={YYYY}/month={MM}/{endpoint}_{YYYYMMDD}.parquet
    """

    def __init__(
        self, base_dir: Path | None = None, *, runtime: DataRuntimeContext | None = None
    ) -> None:
        """初始化 RAW 存储引擎。

        Args:
            base_dir: RAW 数据根目录，若为 None 则默认从 data_settings.raw_data_dir 读取。
            runtime: 可选的统一数据运行时目录上下文。
        """
        active_runtime = runtime or data_settings.runtime_context
        self.base_dir = base_dir if base_dir is not None else active_runtime.raw_root
        self._batch_mode = False
        self._write_buffer: dict[Path, list[tuple[DatasetKey, pl.DataFrame]]] = {}
        self._replace_paths: set[Path] = set()
        self._raw_cache: dict[Path, pl.DataFrame] = {}
        self._raw_dates_cache: dict[Path, set[str] | None] = {}
        self._file_lock = threading.Lock()

    def enable_batch_mode(self) -> None:
        """启用内存攒批模式，延迟到 commit 时再物理落盘，避免 O(N²) 写放大。"""
        self._batch_mode = True
        self._write_buffer = {}
        self._replace_paths = set()
        logger.info("RawDataStorage 已开启攒批写入模式 (Micro-batching)")

    def commit(self) -> None:
        """将内存中缓冲的 RAW 数据原子合并并写入磁盘。"""
        if not getattr(self, "_batch_mode", False) or not getattr(self, "_write_buffer", {}):
            self._batch_mode = False
            return

        logger.info(f"开始提交 RAW 攒批数据，共涉及 {len(self._write_buffer)} 个目标分区...")
        for file_path, dfs in self._write_buffer.items():
            if not dfs:
                continue
            self._merge_and_save(file_path, dfs, replace_existing=file_path in self._replace_paths)
            logger.info(f"RAW 攒批合并落盘成功 -> {file_path}")

        self._write_buffer.clear()
        self._replace_paths.clear()
        self._batch_mode = False
        logger.info("RAW 攒批提交完成，已自动关闭攒批模式。")

    @staticmethod
    def _dataset_name(data_source: str, endpoint: str) -> str:
        """将项目任务或历史兼容名归一为唯一数据集目录名。"""
        return StorageCompat.canonical_dataset_name(endpoint, data_source)

    def _get_partition_dir(self, data_source: str, endpoint: str, target_date: date) -> Path:
        """根据数据源、项目任务与日期计算 Hive 时间分区目录路径。"""
        endpoint = self._dataset_name(data_source, endpoint)
        year_str = f"year={target_date.year:04d}"
        month_str = f"month={target_date.month:02d}"
        return self.base_dir / data_source / endpoint / year_str / month_str

    def _get_file_path(self, data_source: str, endpoint: str, target_date: date) -> Path:
        """计算 RAW 归档文件路径。"""
        endpoint = self._dataset_name(data_source, endpoint)
        partition_dir = self._get_partition_dir(data_source, endpoint, target_date)
        date_str = target_date.strftime("%Y%m%d")
        return partition_dir / f"{endpoint}_{date_str}.parquet"

    def save_raw(
        self, data_source: str, endpoint: str, target_date: date, df: pl.DataFrame
    ) -> Path:
        """保存原始数据帧到 RAW 离线时间分区目录。

        Args:
            data_source: 数据源标识（如 tushare, akshare）。
            endpoint: 接口名称（如 daily, income）。
            target_date: 目标日期。
            df: 包含原始列的 Polars DataFrame。

        Returns:
            Path: 保存的 Parquet 文件路径。
        """
        if df.is_empty():
            logger.warning(f"数据帧为空，跳过 RAW 保存 [{data_source}/{endpoint}]")
            return self._get_file_path(data_source, endpoint, target_date)

        file_path = self._get_file_path(data_source, endpoint, target_date)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        df.write_parquet(file_path)
        logger.info(
            f"RAW 原始数据归档保存成功 [{data_source}/{endpoint}] -> {file_path} ({len(df)} 条记录)"
        )
        return file_path

    def save_dataset(
        self, key: DatasetKey, df: pl.DataFrame, *, replace_existing: bool = False
    ) -> Path:
        """按数据集和月份幂等合并保存 RAW 归档数据。"""
        date_col = _date_column_for_key(key, df)
        if date_col and not df.is_empty() and date_col in RAW_RANGE_DATE_COLUMNS:
            # 按真实业务日期分桶，避免请求 end_date 造成历史快照串区。
            parsed = df.with_columns(parse_mixed_date(date_col).alias("_dt"))
            valid = parsed.filter(pl.col("_dt").is_not_null())
            invalid_count = len(parsed) - len(valid)
            if invalid_count:
                raise DataValidationError(
                    f"RAW 数据集 [{key.provider}/{key.dataset}] 日期列 [{date_col}] "
                    f"包含 {invalid_count} 条无法解析的日期"
                )
            if not valid.is_empty():
                month_series = valid.get_column("_dt").dt.strftime("%Y%m")
                months = month_series.unique().drop_nulls().to_list()
                output = self._get_dataset_path(key)
                for month in months:
                    part = valid.filter(pl.col("_dt").dt.strftime("%Y%m") == month).drop("_dt")
                    y, m = int(month[:4]), int(month[4:6])
                    part_key = DatasetKey(
                        provider=key.provider,
                        dataset=key.dataset,
                        endpoint=key.endpoint,
                        start_date=date(y, m, 1),
                        end_date=date(y, m, 28),
                        instrument=key.instrument,
                        adjustment=key.adjustment,
                        schema_version=key.schema_version,
                    )
                    output = self._save_dataset_file(
                        part_key, part, replace_existing=replace_existing
                    )
                return output
            raise DataValidationError(
                f"RAW 数据集 [{key.provider}/{key.dataset}] 日期列 [{date_col}] 无有效日期"
            )
        return self._save_dataset_file(key, df, replace_existing=replace_existing)

    def _save_dataset_file(
        self, key: DatasetKey, df: pl.DataFrame, *, replace_existing: bool = False
    ) -> Path:
        """保存单个逻辑分区文件。"""
        file_path = self._get_dataset_path(key)
        if df.is_empty():
            return file_path

        if getattr(self, "_batch_mode", False):
            if replace_existing:
                self._replace_paths.add(file_path)
            _append_write_buffer(self._file_lock, self._write_buffer, file_path, (key, df))
            return file_path

        self._merge_and_save(file_path, [(key, df)], replace_existing=replace_existing)
        return file_path

    @staticmethod
    def _backup_legacy_file(file_path: Path) -> None:
        """在替换旧 RAW 文件前保留可恢复副本。"""
        backup_path = file_path.with_name(f"{file_path.stem}.legacy.bak.parquet")
        if backup_path.exists():
            return
        try:
            shutil.copy2(file_path, backup_path)
            logger.warning(f"旧 RAW 文件已保留备份 -> {backup_path}")
        except Exception as exc:
            logger.warning(f"保留旧 RAW 文件备份失败 [{file_path}]: {exc}")

    def _merge_and_save(
        self,
        file_path: Path,
        items: list[tuple[DatasetKey, pl.DataFrame]],
        *,
        replace_existing: bool = False,
    ) -> None:
        """执行物理合并与覆写。"""
        with _shared_file_lock(file_path):
            file_path.parent.mkdir(parents=True, exist_ok=True)
            existing = pl.DataFrame()
            if file_path.exists():
                try:
                    existing = pl.read_parquet(file_path)
                except Exception as e:
                    logger.warning(f"读取原有 RAW 文件失败 [{file_path}]: {e}")
                    self._backup_legacy_file(file_path)

            merged = merge_raw_frames(
                existing,
                items,
                replace_existing=replace_existing,
                backup_legacy_file=lambda: self._backup_legacy_file(file_path),
            )

            temp_path = file_path.with_suffix(f".{threading.get_ident()}.tmp.parquet")
            merged.write_parquet(temp_path)
            temp_path.replace(file_path)
            self._raw_cache.pop(file_path, None)
            self._raw_dates_cache.pop(file_path, None)

    @staticmethod
    def _primary_keys(key: DatasetKey, df: pl.DataFrame) -> list[str]:
        """Resolve registered endpoint keys before falling back to generic identity columns."""
        return resolve_raw_primary_keys(key, df)

    def load_dataset(self, key: DatasetKey) -> pl.DataFrame | None:
        """按数据集和月份读取 RAW 归档数据。"""
        paths = _dataset_paths_for_key(self, key)
        try:
            df = _read_dataset_paths(paths)
            if df is None:
                return None
            if df.is_empty():
                return None
            symbol = key.instrument.symbol if key.instrument is not None else None
            date_col = _date_column_for_key(key, df)
            if date_col:
                values = normalize_raw_date_series(df.get_column(date_col)).str.slice(0, 8)
                start = key.start_date.strftime("%Y%m%d")
                end = key.end_date.strftime("%Y%m%d")
                in_range_mask = (values >= start) & (values <= end)
                if values.filter(in_range_mask).len() == 0:
                    return None
                df = df.filter(in_range_mask)
                values = values.filter(in_range_mask)
            symbol = key.instrument.symbol if key.instrument is not None else None
            if symbol:
                symbol_col = first_existing_column(df, RAW_SYMBOL_COLUMNS)
                if symbol_col:
                    df = df.filter(pl.col(symbol_col).cast(pl.Utf8, strict=False) == str(symbol))
                    if df.is_empty():
                        return None
                    if date_col:
                        values = normalize_raw_date_series(df.get_column(date_col)).str.slice(0, 8)
            if date_col:
                min_value = values.min()
                max_value = values.max()
                if (
                    isinstance(min_value, str)
                    and isinstance(max_value, str)
                    and (min_value > start or max_value < end)
                ):
                    return None
            if key.dataset == "margin" or key.endpoint == "margin":
                if not is_margin_complete(df, start_date=key.start_date, end_date=key.end_date):
                    logger.warning(
                        f"拒绝命中不完整两融 RAW 缓存 [{key.provider}/{key.endpoint}] "
                        f"({key.start_date} ~ {key.end_date})"
                    )
                    return None
            return df
        except Exception as e:
            logger.error(f"读取 RAW 请求缓存失败 [{paths}]: {e}")
            return None

    def _get_dataset_path(self, key: DatasetKey) -> Path:
        """计算 RAW 缓存路径。针对少量/静态/宏观单次数据集，直接存放于数据集根目录。"""
        from stock_data.core.task_registry import is_task_partitioned

        dataset_name = self._dataset_name(key.provider, key.dataset)
        base_dataset_dir = self.base_dir / key.provider / key.market_slug / dataset_name
        if not is_task_partitioned(key.provider, dataset_name):
            return base_dataset_dir / "data.parquet"

        partition_dir = (
            base_dataset_dir / f"year={key.end_date.year:04d}" / f"month={key.end_date.month:02d}"
        )
        return partition_dir / "data.parquet"

    def load_raw(self, data_source: str, endpoint: str, target_date: date) -> pl.DataFrame | None:
        """读取指定日期的 RAW 归档数据。

        Args:
            data_source: 数据源标识。
            endpoint: 接口名称。
            target_date: 目标日期。

        Returns:
            pl.DataFrame | None: 命中的 RAW 数据帧，若无缓存则返回 None。
        """
        file_path = self._get_file_path(data_source, endpoint, target_date)
        if not file_path.exists():
            return None

        try:
            logger.debug(f"读取 RAW 离线缓存: {file_path}")
            return pl.read_parquet(file_path)
        except Exception as e:
            logger.error(f"读取 RAW 归档文件失败 [{file_path}]: {e}")
            return None

    def has_raw(
        self, data_source: str, endpoint: str, target_date: date, symbol: str | None = None
    ) -> bool:
        """判断本地是否存在指定日期的 RAW 归档数据。"""
        return has_raw_cache(self, data_source, endpoint, target_date, symbol)
