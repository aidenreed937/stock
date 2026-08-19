"""Curated 数据按业务日期分区的路由逻辑。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import polars as pl

from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger
from stock_data.core.task_registry import is_task_partitioned, resolve_task
from stock_data.pipeline.cleaner.date_utils import parse_mixed_date


def save_partitioned(
    df: pl.DataFrame,
    dataset_name: str,
    fallback_date: date,
    market_code: str,
    source: str,
    storage_dir: Path,
    path_resolver: Callable[[str, date, str], Path],
    save_single: Callable[
        [Path, pl.DataFrame, str, str, Callable[[Path, pl.DataFrame], None] | None], None
    ],
    cache_updater: Callable[[Path, pl.DataFrame], None] | None = None,
) -> Path:
    """根据数据集属性决定单表落盘或按交易日年月拆分落盘。"""
    if not is_task_partitioned(source, dataset_name):
        file_path = storage_dir / f"market={market_code.upper()}" / dataset_name / "data.parquet"
        save_single(file_path, df, dataset_name, source, cache_updater)
        return file_path

    date_candidates: list[str] = []
    try:
        date_candidates.extend(resolve_task(source, dataset_name).date_columns)
    except Exception:
        pass
    date_candidates.extend(
        column
        for column in (
            "trade_date",
            "ann_date",
            "date",
            "report_date",
            "end_date",
            "as_of_date",
            "publish_date",
            "Date",
        )
        if column not in date_candidates
    )
    date_col = next((column for column in date_candidates if column in df.columns), None)
    if not date_col or df.is_empty():
        file_path = path_resolver(dataset_name, fallback_date, market_code)
        save_single(file_path, df, dataset_name, source, cache_updater)
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
            save_single(file_path, df, dataset_name, source, cache_updater)
            return file_path

        grouped = valid.with_columns(
            [
                pl.col("_dt").dt.year().alias("_y"),
                pl.col("_dt").dt.month().alias("_m"),
            ]
        )
        last_path = None
        for (year, month), sub_df in grouped.partition_by(["_y", "_m"], as_dict=True).items():
            if year is None or month is None:
                continue
            clean_sub = sub_df.drop(["_dt", "_y", "_m"])
            sub_path = path_resolver(dataset_name, date(int(year), int(month), 1), market_code)
            save_single(sub_path, clean_sub, dataset_name, source, cache_updater)
            last_path = sub_path
        return last_path or path_resolver(dataset_name, fallback_date, market_code)
    except DataValidationError:
        raise
    except Exception as exc:
        logger.warning(f"动态按交易日拆分落盘异常，降级使用统一时间分区: {exc}")
        file_path = path_resolver(dataset_name, fallback_date, market_code)
        save_single(file_path, df, dataset_name, source, cache_updater)
        return file_path
