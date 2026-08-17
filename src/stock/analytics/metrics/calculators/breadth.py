"""市场宽度类指标。"""

from datetime import date, timedelta

import polars as pl

from stock.analytics.metrics.context import MetricContext
from stock.analytics.metrics.datasets.loaders import load_metric_dataset
from stock.analytics.metrics.rules import (
    above_ma,
    at_rolling_high,
    at_rolling_low,
    daily_return,
    share,
)
from stock.analytics.metrics.spec import EntityType, MetricCalculator, MetricDomain, MetricSpec

_MA_WINDOWS = (20, 60, 120)
_NEW_HIGH_LOW_WINDOW = 252
_CALENDAR_BUFFER_MULTIPLIER = 3


def _empty(columns: tuple[str, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        schema={column: pl.Date if column == "trade_date" else pl.Float64 for column in columns}
    )


def _require_columns(df: pl.DataFrame, columns: tuple[str, ...], dataset: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{dataset} 缺少字段: {', '.join(missing)}")


def _load_start_date(context: MetricContext, max_window: int) -> date | None:
    end_date = context.resolve_end_date()
    if end_date is None:
        return context.start_date
    lookback_start = end_date - timedelta(days=max_window * _CALENDAR_BUFFER_MULTIPLIER)
    if context.start_date is None:
        return lookback_start
    return min(context.start_date, lookback_start)


def _breadth_frame(context: MetricContext) -> pl.DataFrame:
    start_date = _load_start_date(context, _NEW_HIGH_LOW_WINDOW)
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "breadth", start_date, end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    raw = load_metric_dataset(
        context,
        "stock_daily_bar",
        start_date=start_date,
        end_date=end_date,
        columns=["trade_date", "symbol", "close"],
    )
    if raw.is_empty():
        frame = pl.DataFrame()
    else:
        _require_columns(raw, ("trade_date", "symbol", "close"), "stock_daily_bar")
        frame = _calculate_breadth_columns(raw)

    context.cache[cache_key] = frame
    return frame


def _calculate_breadth_columns(raw: pl.DataFrame) -> pl.DataFrame:
    signals = _stock_signal_frame(raw)
    daily_counts = signals.group_by("trade_date").agg(
        pl.col("symbol").n_unique().alias("total_stocks"),
        pl.col("_return_1d").count().alias("_return_count"),
        (pl.col("_return_1d") > 0).sum().alias("_advance_count"),
        (pl.col("_return_1d") < 0).sum().alias("_decline_count"),
        pl.col("_above_ma20").sum().alias("_above_ma20_count"),
        pl.col("_above_ma20").count().alias("_ma20_count"),
        pl.col("_above_ma60").sum().alias("_above_ma60_count"),
        pl.col("_above_ma60").count().alias("_ma60_count"),
        pl.col("_above_ma120").sum().alias("_above_ma120_count"),
        pl.col("_above_ma120").count().alias("_ma120_count"),
        pl.col("_new_high_252d").sum().alias("_new_high_count"),
        pl.col("_new_high_252d").count().alias("_high_low_count"),
        pl.col("_new_low_252d").sum().alias("_new_low_count"),
    )
    return _with_breadth_metrics(daily_counts).sort("trade_date")


def _stock_signal_frame(raw: pl.DataFrame) -> pl.DataFrame:
    base = (
        raw.select(
            "trade_date",
            pl.col("symbol").cast(pl.String),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .filter(pl.col("close") > 0)
        .sort(["symbol", "trade_date"])
    )
    return base.with_columns(
        daily_return("close").alias("_return_1d"),
        above_ma("close", 20).alias("_above_ma20"),
        above_ma("close", 60).alias("_above_ma60"),
        above_ma("close", 120).alias("_above_ma120"),
        at_rolling_high("close", _NEW_HIGH_LOW_WINDOW).alias("_new_high_252d"),
        at_rolling_low("close", _NEW_HIGH_LOW_WINDOW).alias("_new_low_252d"),
    )


def _with_breadth_metrics(daily_counts: pl.DataFrame) -> pl.DataFrame:
    return daily_counts.with_columns(
        share("_advance_count", "_decline_count", "advance_decline_ratio"),
        share("_advance_count", "_return_count", "advance_share"),
        share("_above_ma20_count", "_ma20_count", "above_ma20_share"),
        share("_above_ma60_count", "_ma60_count", "above_ma60_share"),
        share("_above_ma120_count", "_ma120_count", "above_ma120_share"),
        share("_new_high_count", "_high_low_count", "new_high_share_252d"),
        share("_new_low_count", "_high_low_count", "new_low_share_252d"),
    )


def _select_metric(frame: pl.DataFrame, spec: MetricSpec) -> pl.DataFrame:
    return (
        frame.select(spec.output_columns)
        if not frame.is_empty() and set(spec.output_columns).issubset(frame.columns)
        else _empty(spec.output_columns)
    )


def calculate_breadth_metric(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _breadth_frame(context)
    if context.start_date is not None and not frame.is_empty():
        frame = frame.filter(pl.col("trade_date") >= context.start_date)
    return _select_metric(frame, spec)


def _spec(metric_id: str, name: str, windows: tuple[int, ...] = ()) -> MetricSpec:
    return MetricSpec(
        metric_id=metric_id,
        name=name,
        domain=MetricDomain.BREADTH,
        entity_type=EntityType.MARKET,
        windows=windows,
        required_datasets=("stock_daily_bar",),
        output_columns=("trade_date", metric_id),
    )


METRIC_SPECS: tuple[MetricSpec, ...] = (
    _spec("advance_decline_ratio", "上涨下跌家数比"),
    _spec("advance_share", "上涨家数占比"),
    _spec("above_ma20_share", "站上20日均线占比", (20,)),
    _spec("above_ma60_share", "站上60日均线占比", (60,)),
    _spec("above_ma120_share", "站上120日均线占比", (120,)),
    _spec("new_high_share_252d", "252日新高家数占比", (_NEW_HIGH_LOW_WINDOW,)),
    _spec("new_low_share_252d", "252日新低家数占比", (_NEW_HIGH_LOW_WINDOW,)),
)

CALCULATORS: dict[str, MetricCalculator] = {
    spec.metric_id: calculate_breadth_metric for spec in METRIC_SPECS
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
