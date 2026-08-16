"""RAW 缓存命中检查辅助函数。"""

from datetime import date
from typing import Any

import polars as pl

from stock.data.quality.margin_coverage import is_margin_date_complete
from stock.data.storage.raw_schema import (
    RAW_ARTIFACT_SUFFIXES,
    RAW_RANGE_DATE_COLUMNS,
    RAW_SYMBOL_COLUMNS,
    first_existing_column,
    normalize_raw_date_series,
)
from stock.data.task_registry import get_endpoint_market, resolve_task
from stock.utils.logger import logger


def _legacy_raw_has_symbol(storage: Any, path: Any, symbol: str | None) -> bool:
    if not symbol:
        return True
    try:
        df = pl.read_parquet(path)
    except Exception as e:
        logger.warning(f"读取 RAW legacy 标的检查文件失败 [{path}]: {e}")
        return False
    symbol_col = first_existing_column(df, RAW_SYMBOL_COLUMNS)
    if symbol_col is None:
        return False
    return not df.filter(pl.col(symbol_col).cast(pl.Utf8, strict=False) == str(symbol)).is_empty()


def _candidate_dates(target_date: date) -> set[str]:
    dates = {target_date.strftime("%Y%m%d")}
    try:
        from stock.data.update_scheduler import DataUpdateScheduler

        latest_trading_date = DataUpdateScheduler.get_latest_trading_date(target_date)
        if latest_trading_date is not None:
            dates.add(latest_trading_date.strftime("%Y%m%d"))
    except Exception as exc:
        logger.debug(f"获取最近交易日失败，仅检查目标日期 [{target_date}]: {exc}")
    return dates


def _read_raw_dates(storage: Any, path: Any) -> set[str] | None:
    dates_cache: dict[Any, set[str] | None] = storage._raw_dates_cache
    if path in dates_cache:
        return dates_cache[path]
    try:
        df = pl.read_parquet(path)
        date_col = first_existing_column(df, RAW_RANGE_DATE_COLUMNS)
        if date_col is None:
            dates_cache[path] = None
        else:
            dates_cache[path] = set(
                normalize_raw_date_series(df.get_column(date_col))
                .str.slice(0, 8)
                .drop_nulls()
                .unique()
                .to_list()
            )
    except Exception as e:
        logger.warning(f"读取 RAW 日期检查文件失败 [{path}]: {e}")
        raise
    return dates_cache[path]


def _raw_path_matches_symbol_date(path: Any, candidate_dates: set[str], symbol: str) -> bool:
    try:
        df = pl.read_parquet(path)
    except Exception as e:
        logger.warning(f"读取 RAW 标的日期检查文件失败 [{path}]: {e}")
        return False
    date_col = first_existing_column(df, RAW_RANGE_DATE_COLUMNS)
    symbol_col = first_existing_column(df, RAW_SYMBOL_COLUMNS)
    if date_col is None or symbol_col is None:
        return False
    values = normalize_raw_date_series(df.get_column(date_col)).str.slice(0, 8)
    matched = df.filter(
        values.is_in(candidate_dates)
        & (pl.col(symbol_col).cast(pl.Utf8, strict=False) == str(symbol))
    )
    return not matched.is_empty()


def _raw_path_matches_symbol(path: Any, symbol: str) -> bool:
    try:
        df = pl.read_parquet(path)
    except Exception as e:
        logger.warning(f"读取 RAW 标的检查文件失败 [{path}]: {e}")
        return False
    symbol_col = first_existing_column(df, RAW_SYMBOL_COLUMNS)
    return bool(
        symbol_col
        and not df.filter(pl.col(symbol_col).cast(pl.Utf8, strict=False) == str(symbol)).is_empty()
    )


def _raw_path_matches_margin_date(path: Any, target_date: date) -> bool:
    try:
        frame = pl.read_parquet(path)
    except Exception as e:
        logger.warning(f"读取 RAW 两融覆盖检查文件失败 [{path}]: {e}")
        return False
    return is_margin_date_complete(frame, target_date)


def _is_margin_endpoint(data_source: str, endpoint: str) -> bool:
    try:
        return resolve_task(data_source, endpoint).dataset == "margin"
    except Exception:
        return endpoint == "margin"


def has_raw_cache(
    storage: Any,
    data_source: str,
    endpoint: str,
    target_date: date,
    symbol: str | None = None,
) -> bool:
    """判断 RAW 缓存是否覆盖指定日期和可选标的。"""
    is_margin = _is_margin_endpoint(data_source, endpoint)
    legacy_path = storage._get_file_path(data_source, endpoint, target_date)
    if legacy_path.exists():
        if is_margin:
            return any(
                _raw_path_matches_margin_date(legacy_path, date.fromisoformat(candidate))
                for candidate in _candidate_dates(target_date)
            )
        return _legacy_raw_has_symbol(storage, legacy_path, symbol)
    source_dir = storage.base_dir / data_source
    if not source_dir.exists():
        return False

    year_month_path = f"year={target_date.year:04d}/month={target_date.month:02d}"
    task = resolve_task(data_source, endpoint)
    market = get_endpoint_market(data_source, task.task_name)
    dataset_dir = source_dir / f"market={market.upper()}" / task.dataset
    candidate_dates = _candidate_dates(target_date)

    candidate_paths = [
        dataset_dir / "data.parquet",
        dataset_dir / year_month_path / "data.parquet",
    ]
    for path in candidate_paths:
        if not path.exists() or path.name.endswith(RAW_ARTIFACT_SUFFIXES):
            continue
        try:
            dates_set = _read_raw_dates(storage, path)
        except Exception:
            continue
        if dates_set is None:
            if is_margin:
                continue
            if not symbol or _raw_path_matches_symbol(path, symbol):
                return True
            continue
        if not any(d in dates_set for d in candidate_dates):
            continue
        if is_margin and not any(
            _raw_path_matches_margin_date(path, date.fromisoformat(candidate))
            for candidate in candidate_dates
        ):
            continue
        if symbol and not _raw_path_matches_symbol_date(path, candidate_dates, symbol):
            continue
        return True

    return False
