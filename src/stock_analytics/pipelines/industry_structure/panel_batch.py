"""行业结构面板的批次行情因子计算。"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.industry_structure.panel_metrics import (
    as_float,
    historical_percentile,
    median_value,
    with_market_columns,
    with_return_columns,
)
from stock_analytics.pipelines.industry_structure.panel_sources import (
    _benchmark_symbol_candidates,
    load_benchmark_return_20d,
    load_dataset,
)

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig


def _market_panel(
    daily: pl.DataFrame,
    config: IndustryStructureConfig,
    as_of_date: date,
    catalog: MarketDataCatalog,
) -> pl.DataFrame:
    if daily.is_empty():
        return pl.DataFrame()
    windows = tuple(sorted({5, 10, 20, 60, 120, *config.windows}))
    enriched = with_return_columns(daily, windows)
    enriched = with_market_columns(enriched, config.main_window)
    latest_date = enriched.filter(pl.col("trade_date") <= as_of_date)["trade_date"].max()
    if not isinstance(latest_date, date):
        return pl.DataFrame()
    latest = enriched.filter(pl.col("trade_date") == latest_date)
    benchmark_return = load_benchmark_return_20d(catalog, config.benchmark, as_of_date)
    if benchmark_return is None:
        benchmark_return = median_value(latest, "return_20d")
    rows: list[dict[str, Any]] = []
    for row in latest.to_dicts():
        code = str(row["industry_code"])
        tcr_history = enriched.filter(pl.col("industry_code") == code)["tcr"].to_list()
        current_tcr = as_float(row.get("tcr"))
        return_20d = as_float(row.get("return_20d"))
        row["as_of_date"] = as_of_date
        row["market_data_date"] = latest_date
        amount_raw = as_float(row.get("amount"))
        row["amount_yi"] = amount_raw / 1e8 if amount_raw is not None else None
        row["tcr_percentile"] = historical_percentile(tcr_history, current_tcr)
        row["relative_return_20d"] = (
            return_20d - benchmark_return
            if return_20d is not None and benchmark_return is not None
            else None
        )
        rows.append(row)
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def _market_panel_batch(
    daily: pl.DataFrame,
    config: IndustryStructureConfig,
    target_dates: tuple[date, ...],
    catalog: MarketDataCatalog,
) -> dict[date, pl.DataFrame]:
    """一次计算行业行情因子，再按基准日切出横截面。"""
    if daily.is_empty() or not target_dates:
        return {}
    windows = tuple(sorted({5, 10, 20, 60, 120, *config.windows}))
    enriched = with_return_columns(daily, windows)
    enriched = with_market_columns(enriched, config.main_window).sort(
        ["trade_date", "industry_code"]
    )
    date_partitions = _partition_by_date(enriched, "trade_date")
    market_dates = sorted(date_partitions)
    history_by_code: dict[str, list[tuple[date, object]]] = {}
    for raw_code, frame in enriched.partition_by("industry_code", as_dict=True).items():
        key = raw_code[0] if isinstance(raw_code, tuple) else raw_code
        history_by_code[str(key)] = list(zip(frame["trade_date"].to_list(), frame["tcr"].to_list()))
    benchmark_dates, benchmark_values = _benchmark_return_batch(
        catalog,
        config.benchmark,
        target_dates,
    )
    results: dict[date, pl.DataFrame] = {}
    for as_of_date in target_dates:
        market_index = bisect_right(market_dates, as_of_date) - 1
        if market_index < 0:
            continue
        latest_date = market_dates[market_index]
        latest = date_partitions[latest_date]
        benchmark_index = bisect_right(benchmark_dates, as_of_date) - 1
        benchmark_return = (
            benchmark_values[benchmark_dates[benchmark_index]]
            if benchmark_index >= 0
            else median_value(latest, "return_20d")
        )
        rows: list[dict[str, Any]] = []
        for row in latest.to_dicts():
            industry_code = str(row["industry_code"])
            current_tcr = as_float(row.get("tcr"))
            return_20d = as_float(row.get("return_20d"))
            tcr_history = [
                value
                for value_date, value in history_by_code.get(industry_code, [])
                if value_date <= latest_date
            ]
            row["as_of_date"] = as_of_date
            row["market_data_date"] = latest_date
            amount_raw = as_float(row.get("amount"))
            row["amount_yi"] = amount_raw / 1e8 if amount_raw is not None else None
            row["tcr_percentile"] = historical_percentile(tcr_history, current_tcr)
            row["relative_return_20d"] = (
                return_20d - benchmark_return
                if return_20d is not None and benchmark_return is not None
                else None
            )
            rows.append(row)
        if rows:
            results[as_of_date] = pl.DataFrame(rows)
    return results


def _partition_by_date(frame: pl.DataFrame, date_column: str) -> dict[date, pl.DataFrame]:
    if frame.is_empty() or date_column not in frame.columns:
        return {}
    result: dict[date, pl.DataFrame] = {}
    for raw_key, partition in frame.partition_by(date_column, as_dict=True).items():
        key = raw_key[0] if isinstance(raw_key, tuple) else raw_key
        if isinstance(key, date):
            result[key] = partition
    return result


def _benchmark_return_batch(
    catalog: MarketDataCatalog,
    benchmark: str,
    target_dates: tuple[date, ...],
) -> tuple[list[date], dict[date, float]]:
    if not benchmark or not target_dates:
        return [], {}
    for symbol in _benchmark_symbol_candidates(benchmark):
        frame = load_dataset(
            catalog,
            "index_daily",
            start_date=min(target_dates) - timedelta(days=120),
            end_date=max(target_dates),
            symbols=[symbol],
            columns=["symbol", "trade_date", "close"],
        )
        if frame.is_empty() or not {"trade_date", "close"}.issubset(frame.columns):
            continue
        values = (
            frame.sort("trade_date")
            .drop_nulls(subset=["close"])
            .with_columns(
                ((pl.col("close") / pl.col("close").shift(20) - 1.0) * 100.0).alias("return_20d")
            )
            .drop_nulls(subset=["return_20d"])
        )
        if values.is_empty():
            continue
        dates = values["trade_date"].to_list()
        return dates, dict(zip(dates, values["return_20d"].cast(pl.Float64).to_list()))
    return [], {}
