"""Parquet 分区写入门面。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.constants import BAR_DATASETS
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger
from stock_data.storage.parquet_merge import (
    merge_and_save_parquet as _merge_and_save_parquet,
)
from stock_data.storage.parquet_merge import (
    validate_frame_source as _validate_frame_source,
)
from stock_data.storage.partition_router import save_partitioned as _save_partitioned

validate_frame_source = _validate_frame_source


def _append_write_buffer(
    lock: threading.Lock,
    write_buffer: dict[Path, list[Any]],
    file_path: Path,
    item: Any,
) -> None:
    with lock:
        write_buffer.setdefault(file_path, []).append(item)


class ParquetPartitionWriter:
    """管理 Curated 批量提交，并委托合并引擎与分区路由处理具体写入。"""

    _BAR_DATASETS = BAR_DATASETS

    def __init__(self, data_source: str | None = None) -> None:
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
            merged = self.merge_and_save_parquet(
                file_path, [df for df, _ in items], source=next(iter(sources))
            )
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
        return _merge_and_save_parquet(
            file_path,
            dfs,
            source=source,
            data_source=self.data_source,
            bar_datasets=self._BAR_DATASETS,
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
        """根据数据集属性决定单表落盘或动态按交易日年月拆分落盘。"""
        return _save_partitioned(
            df=df,
            dataset_name=dataset_name,
            fallback_date=fallback_date,
            market_code=market_code,
            source=source,
            storage_dir=storage_dir,
            path_resolver=path_resolver,
            save_single=self._save_single,
            cache_updater=cache_updater,
        )

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
            return
        merged = self.merge_and_save_parquet(file_path, [df], source=source)
        if cache_updater is not None:
            cache_updater(file_path, merged)
        logger.info(f"精炼数据落盘成功 [{dataset_name}] -> {file_path} ({len(merged)} 行)")
