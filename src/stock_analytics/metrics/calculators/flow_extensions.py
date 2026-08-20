"""资金指标的滚动特征与扩展规格。"""

from __future__ import annotations

import polars as pl

from stock_analytics.metrics.spec import EntityType, MetricDomain, MetricSpec
from stock_analytics.primitives.rules import share

MARGIN_GROWTH_WINDOW = 20
MARGIN_GROWTH_LONG_WINDOW = 60
MONEYFLOW_CUM_WINDOW = 20


def add_cumulative_moneyflow_share(frame: pl.DataFrame) -> pl.DataFrame:
    """添加主力净流入相对成交额的 20 日累计占比。"""
    return frame.with_columns(
        pl.col("main_money_net_inflow")
        .rolling_sum(window_size=MONEYFLOW_CUM_WINDOW, min_samples=MONEYFLOW_CUM_WINDOW)
        .alias("_main_money_net_inflow_20d"),
        pl.col("market_amount")
        .rolling_sum(window_size=MONEYFLOW_CUM_WINDOW, min_samples=MONEYFLOW_CUM_WINDOW)
        .alias("_market_amount_20d"),
    ).with_columns(
        share(
            "_main_money_net_inflow_20d",
            "_market_amount_20d",
            "main_money_net_inflow_share_20d_cum",
        )
    )


FLOW_EXTENSION_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        metric_id="margin_balance_growth_20d",
        name="两融余额20日增长率",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(MARGIN_GROWTH_WINDOW,),
        required_datasets=("margin",),
        output_columns=("trade_date", "margin_balance_growth_20d"),
    ),
    MetricSpec(
        metric_id="margin_balance_growth_60d",
        name="两融余额60日增长率",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(MARGIN_GROWTH_LONG_WINDOW,),
        required_datasets=("margin",),
        output_columns=("trade_date", "margin_balance_growth_60d"),
    ),
    MetricSpec(
        metric_id="main_money_net_inflow_share_20d_cum",
        name="主力净流入20日累计成交占比",
        domain=MetricDomain.FLOW,
        entity_type=EntityType.MARKET,
        windows=(MONEYFLOW_CUM_WINDOW,),
        required_datasets=("moneyflow", "stock_daily_bar"),
        output_columns=("trade_date", "main_money_net_inflow_share_20d_cum"),
    ),
)
