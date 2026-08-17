import polars as pl

from stock.analytics.metrics.context import MetricContext
from stock.analytics.metrics.datasets.loaders import load_metric_dataset
from stock.analytics.metrics.datasets.windows import (
    empty_metric_frame as _empty,
)
from stock.analytics.metrics.datasets.windows import (
    load_start_date as _load_start_date,
)
from stock.analytics.metrics.datasets.windows import (
    require_columns as _require_columns,
)
from stock.analytics.metrics.spec import EntityType, MetricCalculator, MetricDomain, MetricSpec

_RSI_WINDOW = 14
_MA_BIAS_WINDOW = 20
_HIGH_DISTANCE_WINDOW = 252


def _trend_frame(context: MetricContext) -> pl.DataFrame:
    start_date = _load_start_date(context, _HIGH_DISTANCE_WINDOW)
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "trend", start_date, end_date)
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
        frame = _calculate_trend_columns(raw)

    context.cache[cache_key] = frame
    return frame


def _calculate_trend_columns(raw: pl.DataFrame) -> pl.DataFrame:
    base = (
        raw.select(
            "trade_date",
            pl.col("symbol").cast(pl.String),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .filter(pl.col("close") > 0)
        .sort(["symbol", "trade_date"])
        .with_columns(
            pl.col("close").rolling_mean(_MA_BIAS_WINDOW).over("symbol").alias("_ma_20d"),
            pl.col("close").rolling_max(_HIGH_DISTANCE_WINDOW).over("symbol").alias("_high_252d"),
            (pl.col("close") - pl.col("close").shift(1).over("symbol")).alias("_diff"),
        )
    )
    return (
        base.with_columns(
            pl.when(pl.col("_diff") > 0).then(pl.col("_diff")).otherwise(0.0).alias("_gain"),
            pl.when(pl.col("_diff") < 0).then(-pl.col("_diff")).otherwise(0.0).alias("_loss"),
        )
        .with_columns(
            pl.col("_gain").rolling_mean(_RSI_WINDOW).over("symbol").alias("_avg_gain"),
            pl.col("_loss").rolling_mean(_RSI_WINDOW).over("symbol").alias("_avg_loss"),
        )
        .with_columns(
            pl.when(pl.col("_ma_20d") > 0)
            .then(pl.col("close") / pl.col("_ma_20d") - 1.0)
            .otherwise(None)
            .alias("ma_bias_20d"),
            pl.when(pl.col("_high_252d") > 0)
            .then(pl.col("close") / pl.col("_high_252d") - 1.0)
            .otherwise(None)
            .alias("distance_to_252d_high"),
            _rsi_expr(),
        )
        .drop(["_ma_20d", "_high_252d", "_diff", "_gain", "_loss", "_avg_gain", "_avg_loss"])
    )


def _rsi_expr() -> pl.Expr:
    rs = pl.col("_avg_gain") / (pl.col("_avg_loss") + 1e-10)
    return (
        pl.when((pl.col("_avg_gain") == 0) & (pl.col("_avg_loss") == 0))
        .then(50.0)
        .otherwise(100.0 - (100.0 / (1.0 + rs)))
        .alias("rsi_14d")
    )


def calculate_trend_metric(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _trend_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    if context.start_date is not None:
        frame = frame.filter(pl.col("trade_date") >= context.start_date)
    return frame.select(spec.output_columns)


def _spec(metric_id: str, name: str, window: int) -> MetricSpec:
    return MetricSpec(
        metric_id=metric_id,
        name=name,
        domain=MetricDomain.TREND,
        entity_type=EntityType.STOCK,
        windows=(window,),
        required_datasets=("stock_daily_bar",),
        output_columns=("trade_date", "symbol", metric_id),
    )


METRIC_SPECS: tuple[MetricSpec, ...] = (
    _spec("ma_bias_20d", "20日均线乖离率", _MA_BIAS_WINDOW),
    _spec("rsi_14d", "14日相对强弱指标", _RSI_WINDOW),
    _spec("distance_to_252d_high", "距252日高点距离", _HIGH_DISTANCE_WINDOW),
)

CALCULATORS: dict[str, MetricCalculator] = {
    spec.metric_id: calculate_trend_metric for spec in METRIC_SPECS
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
