"""资金与筹码类无量纲指标。"""

import polars as pl

from stock.analytics.metrics.calculators.percentile import rolling_percentile
from stock.analytics.metrics.context import MetricContext
from stock.analytics.metrics.datasets.loaders import load_metric_dataset
from stock.analytics.metrics.spec import (
    EntityType,
    MetricCalculator,
    MetricDomain,
    MetricSpec,
)

_TRADING_DAYS_5Y = 1250
_FLOW_ZSCORE_WINDOW = 60
_MARGIN_GROWTH_WINDOW = 20


def _empty(columns: tuple[str, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        schema={column: pl.Date if column == "trade_date" else pl.Float64 for column in columns}
    )


def _first_column(df: pl.DataFrame, candidates: tuple[str, ...], label: str) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    if df.is_empty():
        return None
    raise ValueError(f"{label}缺少字段: {', '.join(candidates)}")


def _load_daily_inputs(context: MetricContext) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    cols_margin = ["trade_date", "rzrqye", "rzye", "rqye", "rzmre", "exchange_id"]
    margin = load_metric_dataset(context, "margin", columns=cols_margin)
    bars = load_metric_dataset(context, "stock_daily_bar", columns=["trade_date", "amount"])
    cols_basic = ["trade_date", "total_mv", "circ_mv"]
    daily_basic = load_metric_dataset(context, "daily_basic", columns=cols_basic)
    return margin, bars, daily_basic


def _load_market_flow_inputs(
    context: MetricContext,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    cols_mf = ["trade_date", "net_mf_amount", "buy_elg_amount", "sell_elg_amount"]
    moneyflow = load_metric_dataset(context, "moneyflow", columns=cols_mf)
    cols_hsgt = ["trade_date", "north_money", "south_money", "hgt", "sgt"]
    hsgt = load_metric_dataset(context, "moneyflow_hsgt", columns=cols_hsgt)
    bars = load_metric_dataset(context, "stock_daily_bar", columns=["trade_date", "amount"])
    return moneyflow, hsgt, bars


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
    net_col = _first_column(moneyflow, ("net_mf_amount", "main_net_inflow"), "moneyflow")
    buy_elg_col = _first_column(moneyflow, ("buy_elg_amount",), "moneyflow")
    sell_elg_col = _first_column(moneyflow, ("sell_elg_amount",), "moneyflow")
    if moneyflow.is_empty() or net_col is None or buy_elg_col is None or sell_elg_col is None:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "main_money_net_inflow": pl.Float64,
                "super_large_net_inflow": pl.Float64,
            }
        )
    return (
        moneyflow.select(
            "trade_date",
            pl.col(net_col).cast(pl.Float64, strict=False).alias("_main_money_net_inflow"),
            pl.col(buy_elg_col).cast(pl.Float64, strict=False).alias("_buy_elg_amount"),
            pl.col(sell_elg_col).cast(pl.Float64, strict=False).alias("_sell_elg_amount"),
        )
        .drop_nulls(subset=["trade_date"])
        .group_by("trade_date")
        .agg(
            pl.col("_main_money_net_inflow").sum().alias("main_money_net_inflow"),
            (pl.col("_buy_elg_amount").sum() - pl.col("_sell_elg_amount").sum()).alias(
                "super_large_net_inflow"
            ),
        )
        .sort("trade_date")
    )


def _northbound_daily(hsgt: pl.DataFrame) -> pl.DataFrame:
    north_col = _first_column(
        hsgt,
        ("north_money",),
        "moneyflow_hsgt",
    )
    if hsgt.is_empty() or north_col is None:
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
            pl.col(north_col).cast(pl.Float64, strict=False).alias("northbound_net_inflow"),
        )
        .drop_nulls(subset=["trade_date"])
        .group_by("trade_date")
        .agg(pl.col("northbound_net_inflow").sum())
        .sort("trade_date")
        .with_columns(_rolling_zscore(pl.DataFrame(), "northbound_net_inflow", _FLOW_ZSCORE_WINDOW))
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


def _base_frame(context: MetricContext) -> pl.DataFrame:
    margin, bars, daily_basic = _load_daily_inputs(context)
    frame = _margin_daily(margin)
    if frame.is_empty():
        return frame
    return (
        frame.join(_market_amount(bars), on="trade_date", how="left")
        .join(_circ_mv(daily_basic), on="trade_date", how="left")
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
            (
                pl.col("margin_balance") / pl.col("margin_balance").shift(_MARGIN_GROWTH_WINDOW)
                - 1.0
            ).alias("margin_balance_growth_20d")
        )
        .sort("trade_date")
    )


def _market_flow_frame(context: MetricContext) -> pl.DataFrame:
    moneyflow, hsgt, bars = _load_market_flow_inputs(context)
    frame = _join_daily_frames(
        (
            _market_amount(bars),
            _main_moneyflow_daily(moneyflow),
            _northbound_daily(hsgt),
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
            "northbound_net_inflow",
            "northbound_net_inflow_zscore_60d",
        ),
    )
    return (
        frame.with_columns(
            pl.when(pl.col("market_amount") > 0)
            .then(pl.col("main_money_net_inflow") / pl.col("market_amount"))
            .otherwise(None)
            .alias("main_money_net_inflow_share"),
            pl.when(pl.col("market_amount") > 0)
            .then(pl.col("super_large_net_inflow") / pl.col("market_amount"))
            .otherwise(None)
            .alias("super_large_net_inflow_share"),
            pl.when(pl.col("market_amount") > 0)
            .then(pl.col("northbound_net_inflow") / pl.col("market_amount"))
            .otherwise(None)
            .alias("northbound_net_inflow_share"),
        )
        .with_columns(_rolling_percentile("market_amount", _TRADING_DAYS_5Y))
        .sort("trade_date")
    )


def _rolling_zscore(df: pl.DataFrame, column: str, window: int) -> pl.Expr:
    mean = pl.col(column).rolling_mean(window_size=window)
    std = pl.col(column).rolling_std(window_size=window)
    return ((pl.col(column) - mean) / (std + 1e-8)).alias(f"{column}_zscore_{window}d")


def _rolling_percentile(column: str, window: int) -> pl.Expr:
    return rolling_percentile(column, f"{column}_percentile_{window}d", window)


def _select_metric(frame: pl.DataFrame, spec: MetricSpec) -> pl.DataFrame:
    return (
        frame.select(spec.output_columns)
        if not frame.is_empty() and set(spec.output_columns).issubset(frame.columns)
        else _empty(spec.output_columns)
    )


def calculate_margin_buy_share(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _base_frame(context)
    return _select_metric(frame, spec)


def calculate_margin_penetration(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _base_frame(context)
    return _select_metric(frame, spec)


def calculate_margin_balance_growth(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _base_frame(context)
    return _select_metric(frame, spec)


def calculate_margin_buy_share_zscore(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _base_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    return _select_metric(frame.with_columns(_rolling_zscore(frame, "margin_buy_share", 60)), spec)


def calculate_margin_penetration_percentile(
    context: MetricContext, spec: MetricSpec
) -> pl.DataFrame:
    frame = _base_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    return _select_metric(frame.with_columns(_rolling_percentile("margin_penetration", 1250)), spec)


def calculate_leverage_sentiment(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
    frame = _base_frame(context)
    if frame.is_empty():
        return _empty(spec.output_columns)
    return (
        frame.with_columns(
            _rolling_zscore(frame, "margin_buy_share", _FLOW_ZSCORE_WINDOW),
            _rolling_zscore(frame, "margin_balance_growth_20d", _FLOW_ZSCORE_WINDOW),
            _rolling_zscore(frame, "margin_penetration", _FLOW_ZSCORE_WINDOW),
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


def calculate_main_money_net_inflow_share(context: MetricContext, spec: MetricSpec) -> pl.DataFrame:
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
        frame.with_columns(
            _rolling_zscore(frame, "main_money_net_inflow_share", _FLOW_ZSCORE_WINDOW)
        ),
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
        metric_id="margin_balance_growth_20d",
        name="两融余额20日增长率",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(_MARGIN_GROWTH_WINDOW,),
        required_datasets=("margin",),
        output_columns=("trade_date", "margin_balance_growth_20d"),
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
        windows=(_MARGIN_GROWTH_WINDOW, _FLOW_ZSCORE_WINDOW),
        required_datasets=("margin", "stock_daily_bar", "daily_basic"),
        output_columns=("trade_date", "leverage_sentiment_score"),
    ),
    MetricSpec(
        metric_id="main_money_net_inflow_share",
        name="主力净流入成交占比",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        required_datasets=("moneyflow", "stock_daily_bar"),
        output_columns=("trade_date", "main_money_net_inflow_share"),
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
        name="全市场成交额五年分位数",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(_TRADING_DAYS_5Y,),
        required_datasets=("stock_daily_bar",),
        output_columns=("trade_date", "market_amount_percentile_1250d"),
    ),
)

CALCULATORS: dict[str, MetricCalculator] = {
    "margin_buy_share": calculate_margin_buy_share,
    "margin_penetration": calculate_margin_penetration,
    "margin_balance_growth_20d": calculate_margin_balance_growth,
    "margin_buy_share_zscore_60d": calculate_margin_buy_share_zscore,
    "margin_penetration_percentile_1250d": calculate_margin_penetration_percentile,
    "leverage_sentiment_score": calculate_leverage_sentiment,
    "main_money_net_inflow_share": calculate_main_money_net_inflow_share,
    "super_large_net_inflow_share": calculate_super_large_net_inflow_share,
    "main_money_net_inflow_share_zscore_60d": calculate_main_money_net_inflow_share_zscore,
    "northbound_net_inflow": calculate_northbound_net_inflow,
    "northbound_net_inflow_share": calculate_northbound_net_inflow_share,
    "northbound_net_inflow_zscore_60d": calculate_northbound_net_inflow_zscore,
    "market_amount_percentile_1250d": calculate_market_amount_percentile,
}

__all__ = ["CALCULATORS", "METRIC_SPECS"]
