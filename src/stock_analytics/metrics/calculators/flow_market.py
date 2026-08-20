"""全市场资金流、北向和成交额指标计算器。"""

from __future__ import annotations

import polars as pl

from stock_analytics.metrics.calculators.flow_extensions import add_cumulative_moneyflow_share
from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.datasets.loaders import load_metric_dataset
from stock_analytics.metrics.datasets.windows import empty_metric_frame as _empty
from stock_analytics.metrics.datasets.windows import first_column as _first_column
from stock_analytics.metrics.spec import EntityType, MetricCalculator, MetricDomain, MetricSpec
from stock_analytics.primitives.rules import rolling_percentile, rolling_zscore, share

_TRADING_DAYS_5Y = 1250
_FLOW_ZSCORE_WINDOW = 60


def _load_market_flow_inputs(
    context: MetricContext,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    moneyflow = load_metric_dataset(
        context,
        "moneyflow",
        columns=[
            "trade_date",
            "net_mf_amount",
            "buy_lg_amount",
            "buy_elg_amount",
            "sell_lg_amount",
            "sell_elg_amount",
        ],
    )
    hsgt = load_metric_dataset(
        context,
        "moneyflow_hsgt",
        columns=["trade_date", "north_money", "south_money", "hgt", "sgt"],
    )
    bars = load_metric_dataset(context, "stock_daily_bar", columns=["trade_date", "amount"])
    daily_basic = load_metric_dataset(context, "daily_basic", columns=["trade_date", "circ_mv"])
    return moneyflow, hsgt, bars, daily_basic


def _market_amount(bars: pl.DataFrame) -> pl.DataFrame:
    if bars.is_empty() or "amount" not in bars.columns:
        return pl.DataFrame(schema={"trade_date": pl.Date, "market_amount": pl.Float64})
    return (
        bars.select(["trade_date", "amount"])
        .drop_nulls()
        .group_by("trade_date")
        .agg(pl.col("amount").sum().alias("market_amount"))
        .sort("trade_date")
    )


def _main_moneyflow_daily(moneyflow: pl.DataFrame) -> pl.DataFrame:
    if moneyflow.is_empty():
        return _empty_main_moneyflow()
    net_col = _first_column(moneyflow, ("net_mf_amount", "main_net_inflow"), "moneyflow")
    buy_elg_col = _first_column(moneyflow, ("buy_elg_amount",), "moneyflow")
    sell_elg_col = _first_column(moneyflow, ("sell_elg_amount",), "moneyflow")
    buy_lg_col = "buy_lg_amount" if "buy_lg_amount" in moneyflow.columns else None
    sell_lg_col = "sell_lg_amount" if "sell_lg_amount" in moneyflow.columns else None
    if net_col is None or buy_elg_col is None or sell_elg_col is None:
        return _empty_main_moneyflow()

    select_exprs = [
        pl.col(net_col).cast(pl.Float64, strict=False).alias("_main_money_net_inflow"),
        pl.col(buy_elg_col).cast(pl.Float64, strict=False).alias("_buy_elg_amount"),
        pl.col(sell_elg_col).cast(pl.Float64, strict=False).alias("_sell_elg_amount"),
    ]
    has_large_order_columns = buy_lg_col is not None and sell_lg_col is not None
    if buy_lg_col is not None and sell_lg_col is not None:
        select_exprs.append(
            (
                pl.col(buy_lg_col).cast(pl.Float64, strict=False)
                + pl.col(buy_elg_col).cast(pl.Float64, strict=False)
                - pl.col(sell_lg_col).cast(pl.Float64, strict=False)
                - pl.col(sell_elg_col).cast(pl.Float64, strict=False)
            ).alias("_main_large_order_net_inflow")
        )
    agg_exprs = [
        pl.col("_main_money_net_inflow").sum().alias("main_money_net_inflow"),
        (pl.col("_buy_elg_amount").sum() - pl.col("_sell_elg_amount").sum()).alias(
            "super_large_net_inflow"
        ),
    ]
    if has_large_order_columns:
        agg_exprs.append(
            pl.col("_main_large_order_net_inflow").sum().alias("main_large_order_net_inflow")
        )
    result = (
        moneyflow.select("trade_date", *select_exprs)
        .drop_nulls(subset=["trade_date"])
        .group_by("trade_date")
        .agg(agg_exprs)
        .sort("trade_date")
    )
    return (
        result
        if has_large_order_columns
        else result.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("main_large_order_net_inflow")
        )
    )


def _empty_main_moneyflow() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "trade_date": pl.Date,
            "main_money_net_inflow": pl.Float64,
            "super_large_net_inflow": pl.Float64,
            "main_large_order_net_inflow": pl.Float64,
        }
    )


def _northbound_daily(hsgt: pl.DataFrame) -> pl.DataFrame:
    if hsgt.is_empty() or "north_money" not in hsgt.columns:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "northbound_net_inflow": pl.Float64,
                "northbound_net_inflow_zscore_60d": pl.Float64,
            }
        )
    return (
        hsgt.select(
            "trade_date",
            pl.col("north_money").cast(pl.Float64, strict=False).alias("northbound_net_inflow"),
        )
        .drop_nulls(subset=["trade_date"])
        .group_by("trade_date")
        .agg(pl.col("northbound_net_inflow").sum())
        .sort("trade_date")
        .with_columns(rolling_zscore("northbound_net_inflow", _FLOW_ZSCORE_WINDOW))
    )


def _circ_mv(daily_basic: pl.DataFrame) -> pl.DataFrame:
    if daily_basic.is_empty() or "circ_mv" not in daily_basic.columns:
        return pl.DataFrame(schema={"trade_date": pl.Date, "circ_mv": pl.Float64})
    return (
        daily_basic.select(["trade_date", "circ_mv"])
        .drop_nulls()
        .group_by("trade_date")
        .agg(pl.col("circ_mv").sum().alias("circ_mv"))
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


def _market_flow_frame(context: MetricContext) -> pl.DataFrame:
    moneyflow, hsgt, bars, daily_basic = _load_market_flow_inputs(context)
    frame = _join_daily_frames(
        (
            _market_amount(bars),
            _main_moneyflow_daily(moneyflow),
            _northbound_daily(hsgt),
            _circ_mv(daily_basic),
        )
    )
    if frame.is_empty():
        return frame
    frame = _with_missing_float_columns(
        frame,
        (
            "market_amount",
            "main_money_net_inflow",
            "super_large_net_inflow",
            "main_large_order_net_inflow",
            "northbound_net_inflow",
            "northbound_net_inflow_zscore_60d",
            "circ_mv",
        ),
    )
    frame = add_cumulative_moneyflow_share(frame)
    return (
        frame.with_columns(
            share("market_amount", "circ_mv", "market_turnover_rate") * 100.0,
            share("main_money_net_inflow", "market_amount", "main_money_net_inflow_share"),
            share(
                "main_large_order_net_inflow",
                "market_amount",
                "main_large_order_net_inflow_share",
            ),
            share("super_large_net_inflow", "market_amount", "super_large_net_inflow_share"),
            share("northbound_net_inflow", "market_amount", "northbound_net_inflow_share"),
        )
        .with_columns(
            rolling_percentile(
                "market_turnover_rate", _TRADING_DAYS_5Y, "market_amount_percentile_1250d"
            )
        )
        .sort("trade_date")
    )


def _select_metric(frame: pl.DataFrame, spec: MetricSpec) -> pl.DataFrame:
    return (
        frame.select(spec.output_columns)
        if not frame.is_empty() and set(spec.output_columns).issubset(frame.columns)
        else _empty(spec.output_columns)
    )


def calculate_main_money_net_inflow_share(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    return _select_metric(_market_flow_frame(context), spec)


def calculate_main_large_order_net_inflow_share(
    context: MetricContext, spec: MetricSpec
) -> pl.DataFrame:
    return _select_metric(_market_flow_frame(context), spec)


def calculate_super_large_net_inflow_share(
    context: MetricContext, spec: MetricSpec
) -> pl.DataFrame:
    return _select_metric(_market_flow_frame(context), spec)


def calculate_main_money_net_inflow_share_zscore(
    context: MetricContext, spec: MetricSpec
) -> pl.DataFrame:
    frame = _market_flow_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    return _select_metric(
        frame.with_columns(rolling_zscore("main_money_net_inflow_share", _FLOW_ZSCORE_WINDOW)),
        spec,
    )


def calculate_northbound_net_inflow(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    return _select_metric(_market_flow_frame(context), spec)


def calculate_northbound_net_inflow_share(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    return _select_metric(_market_flow_frame(context), spec)


def calculate_northbound_net_inflow_zscore(
    context: MetricContext, spec: MetricSpec
) -> pl.DataFrame:
    return _select_metric(_market_flow_frame(context), spec)


def calculate_market_amount_percentile(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    return _select_metric(_market_flow_frame(context), spec)


MARKET_METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        metric_id="main_money_net_inflow_share",
        name="主力净流入成交占比",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        required_datasets=("moneyflow", "stock_daily_bar"),
        output_columns=("trade_date", "main_money_net_inflow_share"),
    ),
    MetricSpec(
        metric_id="main_large_order_net_inflow_share",
        name="主力大单净流入成交占比",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        required_datasets=("moneyflow", "stock_daily_bar"),
        output_columns=("trade_date", "main_large_order_net_inflow_share"),
    ),
    MetricSpec(
        metric_id="super_large_net_inflow_share",
        name="超大单净流入成交占比",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        required_datasets=("moneyflow", "stock_daily_bar"),
        output_columns=("trade_date", "super_large_net_inflow_share"),
    ),
    MetricSpec(
        metric_id="main_money_net_inflow_share_zscore_60d",
        name="主力净流入占比60日Z分数",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(_FLOW_ZSCORE_WINDOW,),
        required_datasets=("moneyflow", "stock_daily_bar"),
        output_columns=("trade_date", "main_money_net_inflow_share_zscore_60d"),
    ),
    MetricSpec(
        metric_id="northbound_net_inflow",
        name="北向净流入额",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        required_datasets=("moneyflow_hsgt",),
        output_columns=("trade_date", "northbound_net_inflow"),
    ),
    MetricSpec(
        metric_id="northbound_net_inflow_share",
        name="北向净流入成交占比",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        required_datasets=("moneyflow_hsgt", "stock_daily_bar"),
        output_columns=("trade_date", "northbound_net_inflow_share"),
    ),
    MetricSpec(
        metric_id="northbound_net_inflow_zscore_60d",
        name="北向净流入60日Z分数",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(_FLOW_ZSCORE_WINDOW,),
        required_datasets=("moneyflow_hsgt",),
        output_columns=("trade_date", "northbound_net_inflow_zscore_60d"),
    ),
    MetricSpec(
        metric_id="market_amount_percentile_1250d",
        name="全市场自由流通换手率五年分位数",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(_TRADING_DAYS_5Y,),
        required_datasets=("stock_daily_bar", "daily_basic"),
        output_columns=("trade_date", "market_amount_percentile_1250d"),
    ),
)

MARKET_CALCULATORS: dict[str, MetricCalculator] = {
    "main_money_net_inflow_share": calculate_main_money_net_inflow_share,
    "main_large_order_net_inflow_share": calculate_main_large_order_net_inflow_share,
    "main_money_net_inflow_share_20d_cum": calculate_main_money_net_inflow_share,
    "super_large_net_inflow_share": calculate_super_large_net_inflow_share,
    "main_money_net_inflow_share_zscore_60d": calculate_main_money_net_inflow_share_zscore,
    "northbound_net_inflow": calculate_northbound_net_inflow,
    "northbound_net_inflow_share": calculate_northbound_net_inflow_share,
    "northbound_net_inflow_zscore_60d": calculate_northbound_net_inflow_zscore,
    "market_amount_percentile_1250d": calculate_market_amount_percentile,
}

__all__ = ["MARKET_CALCULATORS", "MARKET_METRIC_SPECS"]
