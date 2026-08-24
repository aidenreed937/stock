"""行业结构资金流面板。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, cast

import polars as pl

from stock_analytics.pipelines.industry_structure.panel_batch_inputs import (
    IndustryPanelBatchInputs,
    _concat_date_partitions,
)
from stock_analytics.pipelines.industry_structure.panel_sources import (
    load_moneyflow_base_frame,
    load_stock_amount_frame,
    load_stock_industry_map,
)

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig


@dataclass(frozen=True, slots=True)
class IndustryMoneyflowContext:
    """行业资金流特征计算上下文。"""

    config: IndustryStructureConfig
    as_of_date: date
    trade_dates: tuple[date, ...]
    industry_codes: list[object]


def industry_moneyflow_panel(
    cat_ts: MarketDataCatalog,
    cat_lx: MarketDataCatalog,
    context: IndustryMoneyflowContext,
    *,
    batch_inputs: IndustryPanelBatchInputs | None = None,
) -> pl.DataFrame:
    """聚合行业个股资金流净流入与占比指标。"""
    config = context.config
    as_of_date = context.as_of_date
    trade_dates = context.trade_dates
    industry_codes = context.industry_codes
    codes = [str(value) for value in industry_codes if value is not None]
    if not codes or not trade_dates:
        return pl.DataFrame()
    stock_map = (
        batch_inputs.stock_map(as_of_date)
        if batch_inputs is not None
        else load_stock_industry_map(cat_ts, cat_lx, config, as_of_date)
    )
    if stock_map.is_empty():
        return pl.DataFrame({"industry_code": codes})
    window_dates = trade_dates[-config.main_window :]
    window_start = window_dates[0]
    flow = (
        _concat_date_partitions(batch_inputs.moneyflow_by_date, window_start, as_of_date)
        if batch_inputs is not None
        else load_moneyflow_base_frame(cat_ts, window_start, as_of_date)
    )
    if flow.is_empty():
        return pl.DataFrame({"industry_code": codes})
    bars = (
        _concat_date_partitions(batch_inputs.stock_amount_by_date, window_start, as_of_date)
        if batch_inputs is not None
        else load_stock_amount_frame(cat_ts, window_start, as_of_date)
    )
    joined = flow.join(stock_map, on="stock_key", how="inner").filter(
        pl.col("industry_code").is_in(codes)
    )
    if joined.is_empty():
        return pl.DataFrame({"industry_code": codes})
    if not bars.is_empty():
        joined = joined.join(bars, on=["stock_key", "trade_date"], how="left")
    if "_amount" not in joined.columns:
        joined = joined.with_columns(pl.lit(None, dtype=pl.Float64).alias("_amount"))
    latest_flow_date = cast("date", joined["trade_date"].max())
    valid_dates = sorted(
        {value for value in joined["trade_date"].to_list() if value <= latest_flow_date}
    )
    recent5 = set(valid_dates[-5:])
    grouped = (
        joined.with_columns(pl.col("trade_date").is_in(recent5).alias("_is_recent5"))
        .group_by("industry_code")
        .agg(
            pl.col("trade_date").max().alias("moneyflow_date"),
            pl.len().alias("moneyflow_sample_size"),
            pl.col("stock_key").n_unique().alias("moneyflow_stock_count"),
            pl.col("_net_amount").sum().alias("_net_20d"),
            pl.col("_large_net_amount").sum().alias("_large_net_20d"),
            pl.col("_amount").sum().alias("_amount_20d"),
            pl.col("_net_amount").drop_nulls().len().alias("_net_count_20d"),
            pl.col("_amount").drop_nulls().len().alias("_amount_count_20d"),
            pl.when(pl.col("_is_recent5"))
            .then(pl.col("_net_amount"))
            .otherwise(0.0)
            .sum()
            .alias("_net_5d"),
            pl.when(pl.col("_is_recent5"))
            .then(pl.col("_amount"))
            .otherwise(0.0)
            .sum()
            .alias("_amount_5d"),
            pl.when(pl.col("_is_recent5"))
            .then(pl.col("_net_amount"))
            .otherwise(None)
            .drop_nulls()
            .len()
            .alias("_net_count_5d"),
            pl.when(pl.col("_is_recent5"))
            .then(pl.col("_amount"))
            .otherwise(None)
            .drop_nulls()
            .len()
            .alias("_amount_count_5d"),
        )
        .with_columns(
            pl.when(pl.col("_net_count_20d") > 0)
            .then(pl.col("_net_20d") / 1e8)
            .otherwise(None)
            .alias("money_net_inflow_yi_20d"),
            pl.when(
                (pl.col("_net_count_20d") > 0)
                & (pl.col("_amount_count_20d") > 0)
                & (pl.col("_amount_20d") > 0)
            )
            .then(pl.col("_net_20d") / pl.col("_amount_20d") * 100.0)
            .otherwise(None)
            .alias("money_net_inflow_share_20d"),
            pl.when((pl.col("_amount_count_20d") > 0) & (pl.col("_amount_20d") > 0))
            .then(pl.col("_large_net_20d") / pl.col("_amount_20d") * 100.0)
            .otherwise(None)
            .alias("large_money_net_inflow_share_20d"),
            pl.when(
                (pl.col("_net_count_5d") > 0)
                & (pl.col("_amount_count_5d") > 0)
                & (pl.col("_amount_5d") > 0)
            )
            .then(pl.col("_net_5d") / pl.col("_amount_5d") * 100.0)
            .otherwise(None)
            .alias("money_net_inflow_share_5d"),
        )
    )
    return grouped.select(
        "industry_code",
        "moneyflow_date",
        "moneyflow_sample_size",
        "moneyflow_stock_count",
        "money_net_inflow_yi_20d",
        "money_net_inflow_share_20d",
        "large_money_net_inflow_share_20d",
        "money_net_inflow_share_5d",
    )
