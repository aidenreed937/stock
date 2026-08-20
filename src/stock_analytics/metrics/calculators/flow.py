import polars as pl

from stock_analytics.metrics.calculators.flow_extensions import (
    FLOW_EXTENSION_SPECS,
    MARGIN_GROWTH_LONG_WINDOW,
    MARGIN_GROWTH_WINDOW,
)
from stock_analytics.metrics.calculators.flow_market import (
    MARKET_CALCULATORS,
    MARKET_METRIC_SPECS,
)
from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.datasets.loaders import load_metric_dataset
from stock_analytics.metrics.datasets.windows import empty_metric_frame as _empty
from stock_analytics.metrics.datasets.windows import first_column as _first_column
from stock_analytics.metrics.spec import EntityType, MetricCalculator, MetricDomain, MetricSpec
from stock_analytics.primitives.rules import growth, rolling_percentile, rolling_zscore

_TRADING_DAYS_5Y = 1250
_FLOW_ZSCORE_WINDOW = 60


def _load_daily_inputs(context: MetricContext) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    cols_margin = ["trade_date", "rzrqye", "rzye", "rqye", "rzmre", "exchange_id"]
    margin = load_metric_dataset(context, "margin", columns=cols_margin)
    bars = load_metric_dataset(context, "stock_daily_bar", columns=["trade_date", "amount"])
    cols_basic = ["trade_date", "total_mv", "circ_mv"]
    daily_basic = load_metric_dataset(context, "daily_basic", columns=cols_basic)
    return margin, bars, daily_basic


def _margin_daily(margin: pl.DataFrame) -> pl.DataFrame:
    balance_col = _first_column(
        margin,
        ("rzrqye", "margin_balance", "total_balance", "balance", "rzye"),
        "margin",
    )
    buy_col = _first_column(
        margin,
        ("rzmre", "margin_buy_amount", "financing_buy_amount"),
        "margin",
    )
    if margin.is_empty() or balance_col is None or buy_col is None:
        return pl.DataFrame(schema={"trade_date": pl.Date})
    return (
        margin.select(["trade_date", balance_col, buy_col])
        .drop_nulls()
        .group_by("trade_date")
        .agg(
            pl.col(balance_col).sum().alias("margin_balance"),
            pl.col(buy_col).sum().alias("margin_buy_amount"),
        )
        .sort("trade_date")
    )


def _base_frame(context: MetricContext) -> pl.DataFrame:
    margin, bars, daily_basic = _load_daily_inputs(context)
    frame = _margin_daily(margin)
    if frame.is_empty():
        return frame
    market_amount = (
        bars.select(["trade_date", "amount"])
        .drop_nulls()
        .group_by("trade_date")
        .agg(pl.col("amount").sum().alias("market_amount"))
        if not bars.is_empty() and "amount" in bars.columns
        else pl.DataFrame(schema={"trade_date": pl.Date, "market_amount": pl.Float64})
    )
    circ_mv = (
        daily_basic.select(["trade_date", "circ_mv"])
        .drop_nulls()
        .group_by("trade_date")
        .agg(pl.col("circ_mv").sum().alias("circ_mv"))
        if not daily_basic.is_empty() and "circ_mv" in daily_basic.columns
        else pl.DataFrame(schema={"trade_date": pl.Date, "circ_mv": pl.Float64})
    )
    return (
        frame.join(market_amount, on="trade_date", how="left")
        .join(circ_mv, on="trade_date", how="left")
        .with_columns(
            pl.when(pl.col("market_amount") > 0)
            .then(pl.col("margin_buy_amount") / pl.col("market_amount"))
            .otherwise(None)
            .alias("margin_buy_share"),
            pl.when(pl.col("circ_mv") > 0)
            .then(pl.col("margin_balance") / pl.col("circ_mv"))
            .otherwise(None)
            .alias("margin_penetration"),
        )
        .with_columns(
            growth("margin_balance", MARGIN_GROWTH_WINDOW),
            growth("margin_balance", MARGIN_GROWTH_LONG_WINDOW),
        )
        .sort("trade_date")
    )


def _select_metric(frame: pl.DataFrame, spec: MetricSpec) -> pl.DataFrame:
    return (
        frame.select(spec.output_columns)
        if not frame.is_empty() and set(spec.output_columns).issubset(frame.columns)
        else _empty(spec.output_columns)
    )


def calculate_margin_buy_share(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    return _select_metric(_base_frame(context), spec)


def calculate_margin_penetration(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    return _select_metric(_base_frame(context), spec)


def calculate_margin_balance_growth(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    return _select_metric(_base_frame(context), spec)


def calculate_margin_buy_share_zscore(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _base_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    return _select_metric(frame.with_columns(rolling_zscore("margin_buy_share", 60)), spec)


def calculate_margin_penetration_percentile(
    context: MetricContext, spec: MetricSpec
) -> pl.DataFrame:
    frame = _base_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    return _select_metric(frame.with_columns(rolling_percentile("margin_penetration", 1250)), spec)


def calculate_leverage_sentiment(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _base_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    return (
        frame.with_columns(
            rolling_zscore("margin_buy_share", _FLOW_ZSCORE_WINDOW),
            rolling_zscore("margin_balance_growth_20d", _FLOW_ZSCORE_WINDOW),
            rolling_zscore("margin_penetration", _FLOW_ZSCORE_WINDOW),
        )
        .with_columns(
            (
                pl.col("margin_buy_share_zscore_60d") * 0.4
                + pl.col("margin_balance_growth_20d_zscore_60d") * 0.3
                + pl.col("margin_penetration_zscore_60d") * 0.3
            ).alias("leverage_sentiment_score")
        )
        .select(["trade_date", "leverage_sentiment_score"])
    )


METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        metric_id="margin_buy_share",
        name="融资买入成交占比",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        required_datasets=("margin", "stock_daily_bar"),
        output_columns=("trade_date", "margin_buy_share"),
    ),
    MetricSpec(
        metric_id="margin_penetration",
        name="两融余额流通市值比",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        required_datasets=("margin", "daily_basic"),
        output_columns=("trade_date", "margin_penetration"),
    ),
    MetricSpec(
        metric_id="margin_buy_share_zscore_60d",
        name="融资买入占比60日Z分数",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(_FLOW_ZSCORE_WINDOW,),
        required_datasets=("margin", "stock_daily_bar"),
        output_columns=("trade_date", "margin_buy_share_zscore_60d"),
    ),
    MetricSpec(
        metric_id="margin_penetration_percentile_1250d",
        name="两融渗透率五年分位数",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(_TRADING_DAYS_5Y,),
        required_datasets=("margin", "daily_basic"),
        output_columns=("trade_date", "margin_penetration_percentile_1250d"),
    ),
    MetricSpec(
        metric_id="leverage_sentiment_score",
        name="杠杆资金情绪指数",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(MARGIN_GROWTH_WINDOW, _FLOW_ZSCORE_WINDOW),
        required_datasets=("margin", "stock_daily_bar", "daily_basic"),
        output_columns=("trade_date", "leverage_sentiment_score"),
    ),
)

METRIC_SPECS += FLOW_EXTENSION_SPECS
METRIC_SPECS += MARKET_METRIC_SPECS

CALCULATORS: dict[str, MetricCalculator] = {
    "margin_buy_share": calculate_margin_buy_share,
    "margin_penetration": calculate_margin_penetration,
    "margin_balance_growth_20d": calculate_margin_balance_growth,
    "margin_balance_growth_60d": calculate_margin_balance_growth,
    "margin_buy_share_zscore_60d": calculate_margin_buy_share_zscore,
    "margin_penetration_percentile_1250d": calculate_margin_penetration_percentile,
    "leverage_sentiment_score": calculate_leverage_sentiment,
    **MARKET_CALCULATORS,
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
