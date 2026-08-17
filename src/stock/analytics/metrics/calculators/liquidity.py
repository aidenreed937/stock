"""流动性与交易热度类指标。"""

from datetime import date, timedelta

import polars as pl

from stock.analytics.metrics.calculators.percentile import rolling_percentile
from stock.analytics.metrics.context import MetricContext
from stock.analytics.metrics.datasets.loaders import load_metric_dataset
from stock.analytics.metrics.spec import EntityType, MetricCalculator, MetricDomain, MetricSpec

_TRADING_DAYS_5Y = 1250
_AMOUNT_MA_WINDOW = 20
_ZSCORE_WINDOW = 60
_CALENDAR_BUFFER_MULTIPLIER = 3


def _empty(columns: tuple[str, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        schema={column: pl.Date if column == "trade_date" else pl.Float64 for column in columns}
    )


def _first_column(df: pl.DataFrame, candidates: tuple[str, ...], dataset: str) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    if df.is_empty():
        return None
    raise ValueError(f"{dataset} 缺少字段: {', '.join(candidates)}")


def _load_start_date(context: MetricContext, max_window: int) -> date | None:
    end_date = context.resolve_end_date()
    if end_date is None:
        return context.start_date
    lookback_start = end_date - timedelta(days=max_window * _CALENDAR_BUFFER_MULTIPLIER)
    if context.start_date is None:
        return lookback_start
    return min(context.start_date, lookback_start)


def _daily_turnover(daily_basic: pl.DataFrame) -> pl.DataFrame:
    turnover_col = _first_column(
        daily_basic,
        ("turnover_rate_f", "turnover_rate", "turnover"),
        "daily_basic",
    )
    if daily_basic.is_empty() or turnover_col is None:
        return pl.DataFrame(schema={"trade_date": pl.Date, "market_turnover_rate": pl.Float64})
    return (
        daily_basic.select(
            "trade_date",
            pl.col(turnover_col).cast(pl.Float64, strict=False).alias("_turnover_rate"),
        )
        .drop_nulls()
        .group_by("trade_date")
        .agg(pl.col("_turnover_rate").mean().alias("market_turnover_rate"))
        .sort("trade_date")
    )


def _market_amount(bars: pl.DataFrame) -> pl.DataFrame:
    if bars.is_empty() or "amount" not in bars.columns:
        return pl.DataFrame(schema={"trade_date": pl.Date, "market_amount": pl.Float64})
    return (
        bars.select("trade_date", pl.col("amount").cast(pl.Float64, strict=False))
        .drop_nulls()
        .group_by("trade_date")
        .agg(pl.col("amount").sum().alias("market_amount"))
        .sort("trade_date")
    )


def _join_daily_frames(frames: tuple[pl.DataFrame, ...]) -> pl.DataFrame:
    non_empty = [frame for frame in frames if not frame.is_empty()]
    if not non_empty:
        return pl.DataFrame(schema={"trade_date": pl.Date})
    frame = non_empty[0]
    for next_frame in non_empty[1:]:
        frame = frame.join(next_frame, on="trade_date", how="full", coalesce=True)
    return frame.sort("trade_date")


def _with_missing_float_columns(df: pl.DataFrame, columns: tuple[str, ...]) -> pl.DataFrame:
    missing = [
        pl.lit(None, dtype=pl.Float64).alias(column)
        for column in columns
        if column not in df.columns
    ]
    return df.with_columns(missing) if missing else df


def _rolling_percentile(column: str, output: str, window: int) -> pl.Expr:
    return rolling_percentile(column, output, window)


def _rolling_zscore(column: str, output: str, window: int) -> pl.Expr:
    mean = pl.col(column).rolling_mean(window_size=window)
    std = pl.col(column).rolling_std(window_size=window)
    return pl.when(std > 0).then((pl.col(column) - mean) / std).otherwise(None).alias(output)


def _liquidity_frame(context: MetricContext) -> pl.DataFrame:
    start_date = _load_start_date(context, _TRADING_DAYS_5Y)
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "liquidity", start_date, end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    daily_basic = load_metric_dataset(
        context,
        "daily_basic",
        start_date=start_date,
        end_date=end_date,
        columns=["trade_date", "turnover_rate_f", "turnover_rate"],
    )
    bars = load_metric_dataset(
        context,
        "stock_daily_bar",
        start_date=start_date,
        end_date=end_date,
        columns=["trade_date", "amount"],
    )
    frame = _join_daily_frames((_daily_turnover(daily_basic), _market_amount(bars)))
    if not frame.is_empty():
        frame = _calculate_liquidity_columns(frame)

    context.cache[cache_key] = frame
    return frame


def _calculate_liquidity_columns(frame: pl.DataFrame) -> pl.DataFrame:
    market_amount_ma = pl.col("market_amount").rolling_mean(window_size=_AMOUNT_MA_WINDOW)
    frame = _with_missing_float_columns(frame, ("market_turnover_rate", "market_amount"))
    return frame.with_columns(
        _rolling_percentile(
            "market_turnover_rate",
            "turnover_rate_percentile_1250d",
            _TRADING_DAYS_5Y,
        ),
        _rolling_zscore("market_turnover_rate", "turnover_rate_zscore_60d", _ZSCORE_WINDOW),
        pl.when(market_amount_ma > 0)
        .then(pl.col("market_amount") / market_amount_ma)
        .otherwise(None)
        .alias("amount_ma_ratio_20d"),
        _rolling_zscore("market_amount", "amount_zscore_60d", _ZSCORE_WINDOW),
    )


def _select_metric(frame: pl.DataFrame, spec: MetricSpec) -> pl.DataFrame:
    return (
        frame.select(spec.output_columns)
        if not frame.is_empty() and set(spec.output_columns).issubset(frame.columns)
        else _empty(spec.output_columns)
    )


def calculate_liquidity_metric(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _liquidity_frame(context)
    if context.start_date is not None and not frame.is_empty():
        frame = frame.filter(pl.col("trade_date") >= context.start_date)
    return _select_metric(frame, spec)


def _spec(
    metric_id: str,
    name: str,
    *,
    windows: tuple[int, ...] = (),
    datasets: tuple[str, ...] = ("daily_basic",),
) -> MetricSpec:
    return MetricSpec(
        metric_id=metric_id,
        name=name,
        domain=MetricDomain.LIQUIDITY,
        entity_type=EntityType.MARKET,
        windows=windows,
        required_datasets=datasets,
        output_columns=("trade_date", metric_id),
    )


METRIC_SPECS: tuple[MetricSpec, ...] = (
    _spec("market_turnover_rate", "全市场平均换手率"),
    _spec(
        "turnover_rate_percentile_1250d",
        "全市场换手率五年分位数",
        windows=(_TRADING_DAYS_5Y,),
    ),
    _spec(
        "turnover_rate_zscore_60d",
        "全市场换手率60日Z分数",
        windows=(_ZSCORE_WINDOW,),
    ),
    _spec(
        "amount_ma_ratio_20d",
        "全市场成交额20日均量比",
        windows=(_AMOUNT_MA_WINDOW,),
        datasets=("stock_daily_bar",),
    ),
    _spec(
        "amount_zscore_60d",
        "全市场成交额60日Z分数",
        windows=(_ZSCORE_WINDOW,),
        datasets=("stock_daily_bar",),
    ),
)

CALCULATORS: dict[str, MetricCalculator] = {
    spec.metric_id: calculate_liquidity_metric for spec in METRIC_SPECS
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
