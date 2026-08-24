"""市场温度计派生事实通用工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_analytics.primitives.rules import percentile_rank
from stock_core.contracts import MarketDataCatalog
from stock_data.pipeline.cleaner.date_utils import parse_mixed_date

if TYPE_CHECKING:
    from datetime import date


def _percentile_metric_row(
    frame: pl.DataFrame,
    metric_id: str,
    value_col: str,
    as_of_date: date,
    *,
    dimension: str = "macro_liquidity",
    date_col: str = "trade_date",
    inverse: bool = False,
    note: str,
) -> dict[str, Any]:
    temp, latest_value, latest_date, sample_size = _percentile_temperature(
        frame,
        value_col,
        as_of_date,
        date_col=date_col,
        inverse=inverse,
    )
    status = "ok" if temp is not None else "insufficient"
    detail = note
    if latest_value is not None and latest_date is not None:
        detail = f"{note}; latest_date={latest_date}; latest_value={latest_value:.6g}"
    return _metric_row(
        dimension,
        metric_id,
        as_of_date,
        temp,
        sample_size=sample_size,
        status=status,
        note=detail,
    )


def _percentile_temperature(
    frame: pl.DataFrame,
    value_col: str,
    as_of_date: date,
    *,
    date_col: str,
    inverse: bool,
) -> tuple[float | None, float | None, date | None, int]:
    if frame.is_empty() or date_col not in frame.columns or value_col not in frame.columns:
        return None, None, None, 0
    data = (
        frame.select(date_col, pl.col(value_col).cast(pl.Float64, strict=False).alias("_value"))
        .drop_nulls()
        .filter(pl.col(date_col) <= as_of_date)
        .sort(date_col)
    )
    if data.is_empty():
        return None, None, None, 0
    latest_value = float(data["_value"][-1])
    percentile = percentile_rank(data["_value"], data.height, current=latest_value)
    if percentile is None:
        return None, latest_value, data[date_col][-1], data.height
    temperature = 100.0 - percentile if inverse else percentile
    return _clip_temperature(temperature), latest_value, data[date_col][-1], data.height


def _positive_share(frame: pl.DataFrame, column: str) -> float | None:
    values = frame.select(pl.col(column).cast(pl.Float64, strict=False)).drop_nulls()
    if values.is_empty():
        return None
    return float(values.select((pl.col(column) > 0).mean()).item()) * 100.0


def _historical_median_temperature(
    frame: pl.DataFrame,
    column: str,
    as_of_date: date,
) -> float | None:
    series = (
        frame.filter(pl.col("trade_date") <= as_of_date)
        .group_by("trade_date")
        .agg(pl.col(column).median().alias("_value"))
        .sort("trade_date")
    )
    temp, _, _, _ = _percentile_temperature(
        series,
        "_value",
        as_of_date,
        date_col="trade_date",
        inverse=False,
    )
    return temp


def _with_month_date(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or "month" not in frame.columns:
        return frame
    return frame.with_columns(
        pl.col("month")
        .cast(pl.String)
        .str.strptime(pl.Date, "%Y%m", strict=False)
        .alias("_month_date")
    )


def _with_social_finance_yoy(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or "stk_endval" not in frame.columns:
        return frame
    return (
        frame.sort("_month_date")
        .with_columns(pl.col("stk_endval").shift(12).alias("_sf_stock_prev_year"))
        .with_columns(
            pl.when(pl.col("_sf_stock_prev_year") > 0)
            .then(pl.col("stk_endval") / pl.col("_sf_stock_prev_year") - 1.0)
            .otherwise(None)
            .alias("_sf_stock_yoy")
        )
    )


def _real_rate_frame(debt: pl.DataFrame, cpi: pl.DataFrame) -> pl.DataFrame:
    if debt.is_empty() or cpi.is_empty():
        return pl.DataFrame()
    bond = (
        debt.with_columns(pl.col("trade_date").dt.strftime("%Y%m").alias("month"))
        .sort("trade_date")
        .group_by("month")
        .tail(1)
        .select(
            pl.col("month"),
            pl.col("trade_date").alias("_month_date"),
            pl.col("tcm_y10").cast(pl.Float64, strict=False).alias("_bond_yield_10y"),
        )
    )
    cpi_frame = cpi.select(
        "month",
        pl.col("nt_yoy").cast(pl.Float64, strict=False).alias("_cpi_yoy"),
    )
    return bond.join(cpi_frame, on="month", how="inner").with_columns(
        (pl.col("_bond_yield_10y") - pl.col("_cpi_yoy") / 100.0).alias("_real_rate")
    )


def _parse_compact_date_expr(column: str) -> pl.Expr:
    return parse_mixed_date(column)


def _load_dataset(
    cat: MarketDataCatalog,
    dataset: str,
    columns: list[str] | None = None,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    dataset_cache: DatasetFrameCache | None = None,
) -> pl.DataFrame:
    try:
        if dataset_cache is not None:
            return dataset_cache.load(
                cat,
                dataset,
                start_date=start_date,
                end_date=end_date,
                columns=columns,
            )
        return load_dataset_compat(
            cat,
            dataset,
            start_date=start_date,
            end_date=end_date,
            columns=columns,
        )
    except Exception:
        return pl.DataFrame()


def _metric_row(
    dimension: str,
    metric_id: str,
    as_of_date: date,
    value: float | None,
    *,
    metric_date: date | None = None,
    sample_size: int | None = None,
    status: str = "ok",
    note: str = "",
    unit: str = "temperature",
    dataset: str = "",
    source: str = "market_temperature.derived",
) -> dict[str, Any]:
    actual_status = status if value is not None else "insufficient"
    return {
        "fact_id": f"metric.{dimension}.{metric_id}",
        "category": "metric_value",
        "dimension": dimension,
        "data_source": "derived",
        "dataset": dataset,
        "as_of_date": as_of_date,
        "window": 0,
        "metric_id": metric_id,
        "value_float": (
            _clip_temperature(value) if value is not None and unit == "temperature" else value
        ),
        "value_text": "",
        "unit": unit,
        "sample_size": sample_size,
        "source": source,
        "status": actual_status,
        "note": note,
        "metric_date": metric_date,
    }


def _clip_temperature(value: float | None) -> float | None:
    if value is None:
        return None
    return min(100.0, max(0.0, float(value)))
