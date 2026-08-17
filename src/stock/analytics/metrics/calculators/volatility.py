from typing import cast

import polars as pl

from stock.analytics.metrics.context import MetricContext
from stock.analytics.metrics.datasets.loaders import load_metric_dataset
from stock.analytics.metrics.datasets.schema import (
    require_columns as _require_columns,
)
from stock.analytics.metrics.datasets.windows import (
    empty_metric_frame as _empty,
)
from stock.analytics.metrics.datasets.windows import (
    load_start_date as _load_start_date,
)
from stock.analytics.metrics.spec import EntityType, MetricCalculator, MetricDomain, MetricSpec

_VOLATILITY_WINDOW = 20
_DRAWDOWN_WINDOW = 60
_ANNUAL_TRADING_DAYS = 252


def _max_drawdown(values: pl.Series) -> float | None:
    if values.is_empty() or values.null_count() > 0:
        return None
    drawdowns = values / values.cum_max() - 1.0
    minimum = drawdowns.min()
    if minimum is None:
        return None
    return float(cast("float", minimum))


def _volatility_frame(context: MetricContext) -> pl.DataFrame:
    start_date = _load_start_date(context, _DRAWDOWN_WINDOW)
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "volatility", start_date, end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    raw = load_metric_dataset(
        context,
        "stock_daily_bar",
        start_date=start_date,
        end_date=end_date,
    )
    if raw.is_empty():
        frame = pl.DataFrame()
    else:
        _require_columns(raw, ("trade_date", "symbol", "close"), "stock_daily_bar")
        frame = _calculate_volatility_columns(raw)

    context.cache[cache_key] = frame
    return frame


def _calculate_volatility_columns(raw: pl.DataFrame) -> pl.DataFrame:
    previous_close = pl.col("close").shift(1).over("symbol")
    downside_return = pl.when(pl.col("_log_return") < 0).then(pl.col("_log_return")).otherwise(0.0)
    downside_square = downside_return * downside_return
    sqrt_days = _ANNUAL_TRADING_DAYS**0.5
    return (
        raw.select(
            "trade_date",
            pl.col("symbol").cast(pl.String),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .filter(pl.col("close") > 0)
        .sort(["symbol", "trade_date"])
        .with_columns(
            pl.when(previous_close > 0)
            .then((pl.col("close") / previous_close).log())
            .otherwise(None)
            .alias("_log_return")
        )
        .with_columns(
            (
                pl.col("_log_return").rolling_std(_VOLATILITY_WINDOW).over("symbol") * sqrt_days
            ).alias("realized_volatility_20d"),
            (
                downside_square.rolling_mean(_VOLATILITY_WINDOW).over("symbol").sqrt() * sqrt_days
            ).alias("downside_volatility_20d"),
            pl.col("close")
            .rolling_map(_max_drawdown, window_size=_DRAWDOWN_WINDOW, min_samples=_DRAWDOWN_WINDOW)
            .over("symbol")
            .alias("max_drawdown_60d"),
        )
        .drop("_log_return")
    )


def calculate_volatility_metric(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _volatility_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    if context.start_date is not None:
        frame = frame.filter(pl.col("trade_date") >= context.start_date)
    return frame.select(spec.output_columns)


def _spec(metric_id: str, name: str, window: int) -> MetricSpec:
    return MetricSpec(
        metric_id=metric_id,
        name=name,
        domain=MetricDomain.VOLATILITY,
        entity_type=EntityType.STOCK,
        windows=(window,),
        required_datasets=("stock_daily_bar",),
        output_columns=("trade_date", "symbol", metric_id),
    )


METRIC_SPECS: tuple[MetricSpec, ...] = (
    _spec("realized_volatility_20d", "20日年化已实现波动率", _VOLATILITY_WINDOW),
    _spec("downside_volatility_20d", "20日年化下行波动率", _VOLATILITY_WINDOW),
    _spec("max_drawdown_60d", "60日最大回撤", _DRAWDOWN_WINDOW),
)

CALCULATORS: dict[str, MetricCalculator] = {
    spec.metric_id: calculate_volatility_metric for spec in METRIC_SPECS
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
