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

_RETURN_WINDOWS = (1, 5, 20, 60, 252)


def _return_expr(window: int) -> pl.Expr:
    previous_close = pl.col("close").shift(window).over("symbol")
    return (
        pl.when(previous_close > 0)
        .then(pl.col("close") / previous_close - 1.0)
        .otherwise(None)
        .alias(f"return_{window}d")
    )


def _performance_frame(context: MetricContext) -> pl.DataFrame:
    start_date = _load_start_date(context, max(_RETURN_WINDOWS))
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "performance", start_date, end_date)
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
        frame = (
            raw.select(
                "trade_date",
                pl.col("symbol").cast(pl.String),
                pl.col("close").cast(pl.Float64, strict=False),
            )
            .drop_nulls()
            .filter(pl.col("close") > 0)
            .sort(["symbol", "trade_date"])
            .with_columns([_return_expr(window) for window in _RETURN_WINDOWS])
        )

    context.cache[cache_key] = frame
    return frame


def calculate_performance_metric(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _performance_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    if context.start_date is not None:
        frame = frame.filter(pl.col("trade_date") >= context.start_date)
    return frame.select(spec.output_columns)


def _spec(metric_id: str, name: str, window: int) -> MetricSpec:
    return MetricSpec(
        metric_id=metric_id,
        name=name,
        domain=MetricDomain.PERFORMANCE,
        entity_type=EntityType.STOCK,
        windows=(window,),
        required_datasets=("stock_daily_bar",),
        output_columns=("trade_date", "symbol", metric_id),
    )


METRIC_SPECS: tuple[MetricSpec, ...] = (
    _spec("return_1d", "1日收益率", 1),
    _spec("return_5d", "5日收益率", 5),
    _spec("return_20d", "20日收益率", 20),
    _spec("return_60d", "60日收益率", 60),
    _spec("return_252d", "252日收益率", 252),
)

CALCULATORS: dict[str, MetricCalculator] = {
    spec.metric_id: calculate_performance_metric for spec in METRIC_SPECS
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
