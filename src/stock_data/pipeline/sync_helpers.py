"""增量同步的水位、标的池与日期语义辅助函数。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import polars as pl

from stock_core.config.loader import load_data_config
from stock_data.catalog import DataCatalog
from stock_data.core.task_registry import _provider_registry, expand_task_targets, resolve_task
from stock_data.pipeline.planner import (
    _filter_supported_symbols,
    _load_curated_symbol_pool,
    _should_expand_single_sync,
)
from stock_data.pipeline.scheduler import DataUpdateScheduler
from stock_data.pipeline.sync_target import (
    next_report_period_end,
    next_watermark_date,
    normalize_watermark_date,
)

INDEX_ENDPOINTS = {
    "index_daily",
    "index_dailybasic",
    "index_weight",
    "global_index_daily",
    "index_daily_bar",
    "index_valuation",
    "index_fundamental",
}
FUND_ENDPOINTS = {"fund_daily", "fund_adj", "fund_share", "etf_share_size"}
YFINANCE_MACRO_SYMBOLS = ["^TNX", "^IRX", "DX-Y.NYB", "GC=F", "CL=F", "HG=F", "^VIX"]
WATERMARK_DATE_COLUMNS = (
    "trade_date",
    "report_date",
    "ann_date",
    "float_date",
    "end_date",
    "publish_date",
    "date",
    "Date",
    "month",
    "quarter",
    "as_of_date",
    "asOfDate",
    "endDate",
    "last_data_date",
    "period",
    "Start Date",
)
REFRESH_WATERMARK_FREQUENCIES = {"static", "event"}


def disabled_endpoints(
    data_source: str, load_config: Callable[[], Any] = load_data_config
) -> set[str]:
    """读取当前账户明确停用的任务。"""
    try:
        data_cfg = load_config()
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("加载停用任务配置失败 [%s]: %s", data_source, exc)
        return set()
    disabled = getattr(data_cfg, "disabled_endpoints", {}) or {}
    return {str(endpoint) for endpoint in disabled.get(data_source, [])}


def configured_max_workers(
    data_source: str, load_config: Callable[[], Any] = load_data_config
) -> int:
    """读取数据源专属并发配置，不可用时回退到通用默认值。"""
    try:
        data_cfg = load_config()
        concurrency = getattr(data_cfg, "concurrency", None)
        configured = getattr(concurrency, f"{data_source}_max_workers", None)
        fallback = getattr(concurrency, "default_max_workers", 4)
        return int(configured if configured is not None else fallback)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "读取同步并发配置失败 [%s]，回退到 4: %s", data_source, exc
        )
        return 4


def sync_symbols_for_task(
    data_source: str,
    endpoint: str,
    load_config: Callable[[], Any] = load_data_config,
    resolve_task_fn: Callable[..., Any] = resolve_task,
) -> list[str]:
    task = resolve_task_fn(data_source, endpoint)
    if task.fetch_mode != "per_symbol" or (
        task.is_single_sync and not _should_expand_single_sync(data_source, task.task_name)
    ):
        return [""]

    try:
        data_cfg = load_config()
        watchlist = getattr(data_cfg.watchlists, data_source, None)
    except Exception:
        watchlist = None

    if data_source in {"yfinance", "alphavantage"} and task.dataset == "macro_indicators":
        return YFINANCE_MACRO_SYMBOLS if data_source == "yfinance" else ["CNH=X"]
    if task.required_pool in {"stock_basic", "fund_basic"}:
        return _load_curated_symbol_pool(data_source, task.required_pool)
    if watchlist is None:
        return []
    if data_source == "fred":
        if task.api_name.upper() != "MACRO_INDICATORS":
            return [task.api_name.upper()]
        return list(getattr(watchlist, "macro_series", []) or [])
    if task.task_name in FUND_ENDPOINTS or task.dataset in FUND_ENDPOINTS:
        return list(getattr(watchlist, "funds", []) or [])
    if task.task_name in INDEX_ENDPOINTS or task.dataset in INDEX_ENDPOINTS:
        indices = list(getattr(watchlist, "indices", []) or [])
        return _filter_supported_symbols(indices, data_source, task.task_name, data_cfg)
    stocks = list(getattr(watchlist, "stocks", []) or [])
    return stocks or list(getattr(watchlist, "all_symbols", []) or [])


def schedule_endpoint(data_source: str, endpoint: str, symbol: str) -> str:
    """为混合频率任务选择实际用于窗口判断的端点元数据。"""
    if data_source == "fred" and endpoint == "macro_indicators" and symbol:
        return symbol
    return endpoint


def watermark_date_column(
    data_source: str,
    endpoint: str,
    resolve_task_fn: Callable[..., Any] = resolve_task,
) -> str:
    """读取任务注册表的主时间字段。"""
    try:
        task = resolve_task_fn(data_source, endpoint)
        meta = _provider_registry(data_source).get(task.api_name)
        date_columns = getattr(meta, "date_columns", ()) if meta else ()
        if date_columns:
            return str(date_columns[0])
    except Exception:
        pass
    return "trade_date"


def next_increment_start(watermark: date, data_source: str, endpoint: str, frequency: str) -> date:
    """按日期字段语义推进增量起点。"""
    try:
        if resolve_task(data_source, endpoint).fetch_mode == "per_period":
            return next_report_period_end(watermark)
    except Exception:
        pass
    date_column = watermark_date_column(data_source, endpoint)
    if (
        date_column in {"month", "quarter"}
        or data_source == "fred"
        or frequency in {"monthly", "quarterly", "weekly"}
    ):
        return next_watermark_date(normalize_watermark_date(watermark, frequency), frequency)
    return watermark + timedelta(days=1)


def parse_watermark_value(value: Any) -> date | None:
    """解析日/周/月/季等历史字段为统一的水位日期。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y%m"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    if len(text) == 6 and text[4] == "Q" and text[5] in "1234":
        return date(int(text[:4]), (int(text[5]) - 1) * 3 + 1, 1)
    return None


def symbol_watermark(
    catalog: DataCatalog, data_source: str, dataset: str, symbol: str
) -> date | None:
    if not symbol:
        latest_dates = catalog.latest_trade_dates(dataset=dataset, n=1)
        return latest_dates[0] if latest_dates else None
    try:
        frame = catalog.load_dataset(dataset, symbols=[symbol])
    except Exception:
        return None
    if frame.is_empty() or "trade_date" not in frame.columns:
        return None
    max_date = frame.get_column("trade_date").max()
    if isinstance(max_date, date):
        return max_date
    if max_date is not None:
        try:
            return date.fromisoformat(str(max_date))
        except ValueError:
            return None
    return None


def symbol_base_date(
    data_source: str,
    symbol: str,
    endpoint: str = "",
    load_config: Callable[[], Any] = load_data_config,
) -> date | None:
    if not symbol:
        return None
    try:
        data_cfg = load_config()
        watchlist = getattr(data_cfg.watchlists, data_source, None)
        get_base_date = getattr(watchlist, "get_base_date", None)
        if callable(get_base_date):
            asset_type = (
                "index"
                if endpoint in INDEX_ENDPOINTS
                else "fund"
                if endpoint in FUND_ENDPOINTS
                else "stock"
            )
            try:
                base_date = get_base_date(symbol, asset_type)
            except TypeError:
                base_date = get_base_date(symbol)
            return base_date if isinstance(base_date, date) else None
    except Exception:
        return None
    return None


def symbol_watermarks(
    catalog: DataCatalog,
    data_source: str,
    dataset: str,
    symbols: list[str],
) -> dict[str, date | None]:
    """一次读取一个数据集的标的水位，避免按标的重复扫描 Parquet。"""
    requested = list(dict.fromkeys(symbol for symbol in symbols if symbol))
    result = dict.fromkeys(requested)
    if not requested:
        return result
    try:
        frame = catalog.load_dataset(
            dataset,
            symbols=requested,
            columns=["symbol", *WATERMARK_DATE_COLUMNS],
        )
    except Exception:
        return result
    if frame.is_empty() or "symbol" not in frame.columns:
        return result
    date_candidates: tuple[str, ...] = WATERMARK_DATE_COLUMNS
    try:
        task = resolve_task(data_source, dataset)
        date_candidates = tuple(dict.fromkeys((*task.date_columns, *date_candidates)))
    except Exception:
        pass
    date_column = next((column for column in date_candidates if column in frame.columns), None)
    if date_column is None:
        return result
    frame = frame.with_columns(
        pl.col(date_column)
        .map_elements(parse_watermark_value, return_dtype=pl.Date)
        .alias("__watermark_date")
    )
    for row in frame.select(["symbol", "__watermark_date"]).drop_nulls().iter_rows(named=True):
        parsed = row["__watermark_date"]
        symbol = str(row["symbol"])
        if (
            symbol in result
            and parsed is not None
            and (result[symbol] is None or parsed > result[symbol])
        ):
            result[symbol] = parsed
    return result


def symbol_refresh_watermarks(
    catalog: DataCatalog,
    data_source: str,
    dataset: str,
    symbols: list[str],
) -> dict[str, date | None]:
    """读取静态/事件按标的任务的刷新水位。"""
    requested = list(dict.fromkeys(symbol for symbol in symbols if symbol))
    result = dict.fromkeys(requested)
    if not requested:
        return result
    try:
        frame = catalog.load_dataset(dataset, symbols=requested, columns=["symbol", "updated_at"])
    except Exception:
        frame = pl.DataFrame()
    if not frame.is_empty() and {"symbol", "updated_at"}.issubset(frame.columns):
        parsed = frame.with_columns(
            pl.col("updated_at")
            .map_elements(parse_watermark_value, return_dtype=pl.Date)
            .alias("__refresh_date")
        )
        for row in parsed.select(["symbol", "__refresh_date"]).drop_nulls().iter_rows(named=True):
            symbol = str(row["symbol"])
            refresh_date = row["__refresh_date"]
            if (
                symbol in result
                and refresh_date is not None
                and (result[symbol] is None or refresh_date > result[symbol])
            ):
                result[symbol] = refresh_date

    latest_refresh_dates = getattr(catalog, "latest_refresh_dates", None)
    if callable(latest_refresh_dates):
        for symbol, watermark in result.items():
            if watermark is not None:
                continue
            try:
                dates = latest_refresh_dates(dataset=dataset, n=1, symbols=[symbol])
                result[symbol] = dates[0] if dates else None
            except Exception:
                continue
    return result


def sniff_watermarks(
    catalog: DataCatalog,
    data_source: str,
    endpoints: list[str] | None,
    disabled_endpoints_fn: Callable[[str], set[str]],
    watermark_date_column_fn: Callable[[str, str], str],
    expand_task_targets_fn: Callable[..., list[str]] = expand_task_targets,
    resolve_task_fn: Callable[..., Any] = resolve_task,
) -> dict[str, date | None]:
    targets = expand_task_targets_fn(data_source, endpoints)
    disabled = disabled_endpoints_fn(data_source)
    watermarks: dict[str, date | None] = {}
    latest_by_dataset: dict[tuple[str, str], date | None] = {}
    for endpoint in targets:
        if endpoint in disabled:
            watermarks[endpoint] = None
            continue
        try:
            task = resolve_task_fn(data_source, endpoint)
            meta = DataUpdateScheduler.get_endpoint_update_meta(data_source, endpoint)
            if meta.frequency in REFRESH_WATERMARK_FREQUENCIES:
                dates = catalog.latest_refresh_dates(dataset=task.dataset, n=1)
                watermarks[endpoint] = dates[0] if dates else None
                continue
            date_column = watermark_date_column_fn(data_source, endpoint)
            cache_key = (task.dataset, date_column)
            if cache_key not in latest_by_dataset:
                kwargs: dict[str, Any] = {"dataset": task.dataset, "n": 1}
                if date_column != "trade_date":
                    kwargs["date_column"] = date_column
                dates = catalog.latest_trade_dates(**kwargs)
                latest_by_dataset[cache_key] = dates[0] if dates else None
            watermarks[endpoint] = latest_by_dataset[cache_key]
        except Exception:
            watermarks[endpoint] = None
    return watermarks
