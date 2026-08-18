from datetime import date, timedelta

import polars as pl

from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.datasets.loaders import load_metric_dataset
from stock_analytics.metrics.datasets.windows import (
    empty_metric_frame as _empty,
)
from stock_analytics.metrics.datasets.windows import (
    first_column as _first_column,
)
from stock_analytics.metrics.spec import (
    EntityType,
    MetricCalculator,
    MetricDomain,
    MetricSpec,
)
from stock_analytics.primitives.rules import rolling_percentile, rolling_zscore

_TRADING_DAYS_5Y = 1250
_CALENDAR_DAYS_5Y_WITH_BUFFER = 365 * 7
_BOND_YIELD_TOLERANCE = timedelta(days=7)
_CROSS_SOURCE_METRICS = {
    "equity_risk_premium",
    "equity_risk_premium_percentile_5y",
    "equity_bond_yield_ratio",
    "dividend_bond_spread",
    "valuation_temperature",
}


def _load_start_date(context: MetricContext) -> date | None:
    end_date = context.resolve_end_date()
    if end_date is None:
        return context.start_date
    lookback_start = end_date - timedelta(days=_CALENDAR_DAYS_5Y_WITH_BUFFER)
    if context.start_date is None:
        return lookback_start
    return min(context.start_date, lookback_start)


def _rolling_percentile(column: str, output: str) -> pl.Expr:
    return rolling_percentile(column, _TRADING_DAYS_5Y, output).over("symbol")


def _rolling_zscore(column: str, output: str) -> pl.Expr:
    return rolling_zscore(column, _TRADING_DAYS_5Y, output).over("symbol")


def _valuation_frame(context: MetricContext) -> pl.DataFrame:
    start_date = _load_start_date(context)
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "valuation", start_date, end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    raw = load_metric_dataset(
        context,
        "index_fundamental",
        data_source="lixinger",
        start_date=start_date,
        end_date=end_date,
    )
    if raw.is_empty():
        frame = pl.DataFrame()
    else:
        pe_col = _first_column(
            raw,
            ("pe_ttm.mcw", "pe_ttm.ew", "pe_ttm", "pe"),
            "index_fundamental",
        )
        pb_col = _first_column(raw, ("pb.mcw", "pb.ew", "pb"), "index_fundamental")
        dividend_col = _first_column(
            raw,
            ("dyr.mcw", "dyr.ew", "dividend_yield", "dv_ttm"),
            "index_fundamental",
        )
        frame = (
            raw.select(
                "trade_date",
                pl.col("symbol").cast(pl.String),
                pl.col(pe_col).cast(pl.Float64).alias("pe_ttm"),
                pl.col(pb_col).cast(pl.Float64).alias("pb"),
                pl.col(dividend_col).cast(pl.Float64).alias("dividend_yield"),
            )
            .filter((pl.col("pe_ttm") > 0) & (pl.col("pb") > 0) & (pl.col("dividend_yield") >= 0))
            .drop_nulls()
            .sort(["symbol", "trade_date"])
            .with_columns((1.0 / pl.col("pe_ttm")).alias("earnings_yield"))
            .with_columns(
                _rolling_zscore("pe_ttm", "pe_zscore_5y"),
                _rolling_zscore("pb", "pb_zscore_5y"),
                _rolling_percentile("pe_ttm", "pe_percentile_5y"),
                _rolling_percentile("pb", "pb_percentile_5y"),
                _rolling_percentile("dividend_yield", "dividend_yield_percentile_5y"),
            )
        )
    context.cache[cache_key] = frame
    return frame


def _cross_source_frame(context: MetricContext) -> pl.DataFrame:
    start_date = _load_start_date(context)
    end_date = context.resolve_end_date()
    cache_key = context.cache_key("metrics", "valuation_cross_source", start_date, end_date)
    if cache_key in context.cache:
        return context.cache[cache_key]

    valuation = _valuation_frame(context)
    raw_bond = load_metric_dataset(
        context,
        "national_debt",
        data_source="lixinger",
        start_date=start_date,
        end_date=end_date,
    )
    if valuation.is_empty() or raw_bond.is_empty():
        frame = pl.DataFrame()
    else:
        bond_col = _first_column(
            raw_bond,
            ("tcm_y10", "ten_y", "10y", "y10", "yield_10y"),
            "national_debt",
        )
        bond = (
            raw_bond.select(
                pl.col("trade_date").alias("bond_trade_date"),
                pl.col(bond_col).cast(pl.Float64).alias("bond_yield_10y"),
            )
            .filter(pl.col("bond_yield_10y") > 0)
            .with_columns(
                pl.when(pl.col("bond_yield_10y") > 0.2)
                .then(pl.col("bond_yield_10y") / 100.0)
                .otherwise(pl.col("bond_yield_10y"))
                .alias("bond_yield_10y")
            )
            .sort("bond_trade_date")
        )
        frame = (
            valuation.sort("trade_date")
            .join_asof(
                bond,
                left_on="trade_date",
                right_on="bond_trade_date",
                strategy="backward",
                tolerance=_BOND_YIELD_TOLERANCE,
            )
            .with_columns(
                (pl.col("earnings_yield") - pl.col("bond_yield_10y")).alias("equity_risk_premium"),
                (pl.col("earnings_yield") / pl.col("bond_yield_10y")).alias(
                    "equity_bond_yield_ratio"
                ),
                (pl.col("dividend_yield") - pl.col("bond_yield_10y")).alias("dividend_bond_spread"),
            )
            .sort(["symbol", "trade_date"])
            .with_columns(
                _rolling_percentile("equity_risk_premium", "equity_risk_premium_percentile_5y")
            )
            .with_columns(
                pl.when(
                    pl.all_horizontal(
                        pl.col("pe_percentile_5y").is_not_null(),
                        pl.col("pb_percentile_5y").is_not_null(),
                        pl.col("equity_risk_premium_percentile_5y").is_not_null(),
                        pl.col("dividend_yield_percentile_5y").is_not_null(),
                    )
                )
                .then(
                    pl.mean_horizontal(
                        "pe_percentile_5y",
                        "pb_percentile_5y",
                        100.0 - pl.col("equity_risk_premium_percentile_5y"),
                        100.0 - pl.col("dividend_yield_percentile_5y"),
                    )
                )
                .otherwise(None)
                .alias("valuation_temperature")
            )
        )
    context.cache[cache_key] = frame
    return frame


def calculate_valuation_metric(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = (
        _cross_source_frame(context)
        if spec.metric_id in _CROSS_SOURCE_METRICS
        else _valuation_frame(context)
    )
    if frame.is_empty():
        return _empty(spec.output_columns)
    if context.start_date is not None:
        frame = frame.filter(pl.col("trade_date") >= context.start_date)
    return frame.select("trade_date", "symbol", spec.metric_id)


def _spec(
    metric_id: str,
    name: str,
    *,
    datasets: tuple[str, ...] = ("index_fundamental",),
    windows: tuple[int, ...] = (),
) -> MetricSpec:
    return MetricSpec(
        metric_id=metric_id,
        name=name,
        domain=MetricDomain.VALUATION,
        entity_type=EntityType.INDEX,
        windows=windows,
        required_datasets=datasets,
        output_columns=("trade_date", "symbol", metric_id),
    )


METRIC_SPECS: tuple[MetricSpec, ...] = (
    _spec("earnings_yield", "盈利收益率"),
    _spec("pe_zscore_5y", "PE五年Z分数", windows=(_TRADING_DAYS_5Y,)),
    _spec("pb_zscore_5y", "PB五年Z分数", windows=(_TRADING_DAYS_5Y,)),
    _spec("pe_percentile_5y", "PE五年历史分位数", windows=(_TRADING_DAYS_5Y,)),
    _spec("pb_percentile_5y", "PB五年历史分位数", windows=(_TRADING_DAYS_5Y,)),
    _spec(
        "dividend_yield_percentile_5y",
        "股息率五年历史分位数",
        windows=(_TRADING_DAYS_5Y,),
    ),
    _spec(
        "equity_risk_premium",
        "股权风险溢价",
        datasets=("index_fundamental", "national_debt"),
    ),
    _spec(
        "equity_risk_premium_percentile_5y",
        "股权风险溢价五年历史分位数",
        datasets=("index_fundamental", "national_debt"),
        windows=(_TRADING_DAYS_5Y,),
    ),
    _spec(
        "equity_bond_yield_ratio",
        "股债收益比",
        datasets=("index_fundamental", "national_debt"),
    ),
    _spec(
        "dividend_bond_spread",
        "股息率国债利差",
        datasets=("index_fundamental", "national_debt"),
    ),
    _spec(
        "valuation_temperature",
        "估值温度",
        datasets=("index_fundamental", "national_debt"),
        windows=(_TRADING_DAYS_5Y,),
    ),
)

CALCULATORS: dict[str, MetricCalculator] = {
    spec.metric_id: calculate_valuation_metric for spec in METRIC_SPECS
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
