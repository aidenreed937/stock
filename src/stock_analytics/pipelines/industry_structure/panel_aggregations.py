"""行业结构分析面板基本面快报与资金流横截面聚合。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, cast

import polars as pl

from stock_analytics.pipelines.industry_structure.panel_batch_inputs import (
    IndustryPanelBatchInputs,
    _concat_date_partitions,
    _filter_target_period_if_available,
    _latest_completed_report_period,
    _prepare_express_frame,
    _prepare_express_values,
    _prepare_forecast_frame,
    _prepare_forecast_values,
    _prepare_report_revision_frame,
)
from stock_analytics.pipelines.industry_structure.panel_sources import (
    load_dataset,
    load_moneyflow_base_frame,
    load_stock_amount_frame,
    load_stock_industry_map,
)

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig


@dataclass(frozen=True, slots=True)
class FastFundamentalContext:
    """快速基本面特征计算上下文。"""

    config: IndustryStructureConfig
    as_of_date: date
    trade_dates: tuple[date, ...]
    industry_codes: list[object]


@dataclass(frozen=True, slots=True)
class IndustryMoneyflowContext:
    """行业资金流特征计算上下文。"""

    config: IndustryStructureConfig
    as_of_date: date
    trade_dates: tuple[date, ...]
    industry_codes: list[object]


def fast_fundamental_panel(
    cat_ts: MarketDataCatalog,
    cat_lx: MarketDataCatalog,
    context: FastFundamentalContext,
    *,
    batch_inputs: IndustryPanelBatchInputs | None = None,
) -> pl.DataFrame:
    """聚合预告、快报与研报上修的快速确认基本面指标。"""
    codes = [str(value) for value in context.industry_codes if value is not None]
    if not codes:
        return pl.DataFrame()
    stock_map = (
        batch_inputs.stock_map(context.as_of_date)
        if batch_inputs is not None
        else load_stock_industry_map(cat_ts, cat_lx, context.config, context.as_of_date)
    )
    if stock_map.is_empty():
        return pl.DataFrame({"industry_code": codes})
    if len(context.trade_dates) >= context.config.main_window:
        window_start = context.trade_dates[-context.config.main_window]
    else:
        window_start = context.trade_dates[0]
    target_period = _latest_completed_report_period(context.as_of_date)
    panel = pl.DataFrame({"industry_code": codes})
    for frame in (
        _forecast_panel(
            cat_ts,
            stock_map,
            window_start,
            context.as_of_date,
            target_period,
            prepared_by_date=batch_inputs.forecast_by_date if batch_inputs else None,
        ),
        _express_panel(
            cat_ts,
            stock_map,
            window_start,
            context.as_of_date,
            target_period,
            prepared_by_date=batch_inputs.express_by_date if batch_inputs else None,
        ),
        _report_revision_panel(
            cat_ts,
            stock_map,
            window_start,
            context.as_of_date,
            prepared_by_date=batch_inputs.report_revision_by_date if batch_inputs else None,
        ),
    ):
        if not frame.is_empty():
            panel = panel.join(frame, on="industry_code", how="left")
    return panel


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


def _forecast_panel(
    catalog: MarketDataCatalog,
    stock_map: pl.DataFrame,
    window_start: date,
    as_of_date: date,
    target_period: date,
    *,
    prepared_by_date: dict[date, pl.DataFrame] | None = None,
) -> pl.DataFrame:
    if prepared_by_date is None:
        raw = load_dataset(
            catalog,
            "forecast",
            columns=[
                "symbol",
                "ann_date",
                "end_date",
                "type",
                "p_change_min",
                "p_change_max",
            ],
        )
        base = _prepare_forecast_frame(raw)
    else:
        base = _concat_date_partitions(prepared_by_date, window_start, as_of_date)
    if base.is_empty():
        return pl.DataFrame()
    base = base.filter((pl.col("ann_date") >= window_start) & (pl.col("ann_date") <= as_of_date))
    base = _filter_target_period_if_available(base, "end_date", target_period)
    if base.is_empty():
        return pl.DataFrame()
    if "_p_change_mid" not in base.columns:
        base = _prepare_forecast_values(base)
    base = (
        base.sort(["stock_key", "end_date", "ann_date"]).group_by(["stock_key", "end_date"]).tail(1)
    )
    joined = base.join(stock_map, on="stock_key", how="inner")
    if joined.is_empty():
        return pl.DataFrame()
    return joined.group_by("industry_code").agg(
        pl.col("ann_date").max().alias("forecast_date"),
        pl.col("stock_key").n_unique().alias("forecast_sample_size"),
        (pl.col("_positive").mean() * 100.0).alias("forecast_positive_share"),
        pl.col("_p_change_mid").median().alias("forecast_p_change_mid_median"),
    )


def _express_panel(
    catalog: MarketDataCatalog,
    stock_map: pl.DataFrame,
    window_start: date,
    as_of_date: date,
    target_period: date,
    *,
    prepared_by_date: dict[date, pl.DataFrame] | None = None,
) -> pl.DataFrame:
    if prepared_by_date is None:
        raw = load_dataset(
            catalog,
            "express",
            columns=[
                "symbol",
                "ann_date",
                "end_date",
                "n_income",
                "prior_period_net_profit",
                "diluted_roe",
            ],
        )
        base = _prepare_express_frame(raw)
    else:
        base = _concat_date_partitions(prepared_by_date, window_start, as_of_date)
    if base.is_empty():
        return pl.DataFrame()
    base = base.filter((pl.col("ann_date") >= window_start) & (pl.col("ann_date") <= as_of_date))
    base = _filter_target_period_if_available(base, "end_date", target_period)
    if base.is_empty():
        return pl.DataFrame()
    if "_profit_growth" not in base.columns:
        base = _prepare_express_values(base)
    base = (
        base.sort(["stock_key", "end_date", "ann_date"]).group_by(["stock_key", "end_date"]).tail(1)
    )
    joined = base.join(stock_map, on="stock_key", how="inner")
    if joined.is_empty():
        return pl.DataFrame()
    return joined.group_by("industry_code").agg(
        pl.col("ann_date").max().alias("express_date"),
        pl.col("stock_key").n_unique().alias("express_sample_size"),
        pl.col("_profit_growth").median().alias("express_profit_growth_median"),
        pl.col("diluted_roe").median().alias("express_roe_median"),
    )


def _report_revision_panel(
    catalog: MarketDataCatalog,
    stock_map: pl.DataFrame,
    window_start: date,
    as_of_date: date,
    *,
    prepared_by_date: dict[date, pl.DataFrame] | None = None,
) -> pl.DataFrame:
    if prepared_by_date is None:
        raw = load_dataset(
            catalog,
            "report_rc",
            columns=["symbol", "report_date", "org_name", "quarter", "np"],
        )
        base = _prepare_report_revision_frame(raw)
    else:
        base = _concat_date_partitions(prepared_by_date, window_start, as_of_date)
    if base.is_empty():
        return pl.DataFrame()
    if prepared_by_date is None:
        base = base.filter(pl.col("report_date") <= as_of_date)
    else:
        base = base.filter(
            (pl.col("report_date") >= window_start) & (pl.col("report_date") <= as_of_date)
        )
    if base.is_empty():
        return pl.DataFrame()
    window = base.drop_nulls(subset=["_prev_np"])
    if window.is_empty():
        return pl.DataFrame()
    window = window.with_columns(
        (pl.col("np") > pl.col("_prev_np")).cast(pl.Int64).alias("_up"),
        (pl.col("np") < pl.col("_prev_np")).cast(pl.Int64).alias("_down"),
    )
    joined = window.join(stock_map, on="stock_key", how="inner")
    if joined.is_empty():
        return pl.DataFrame()
    grouped = joined.group_by("industry_code").agg(
        pl.col("report_date").max().alias("report_rc_date"),
        pl.len().alias("report_rc_sample_size"),
        pl.col("_up").sum().alias("report_rc_up_count"),
        pl.col("_down").sum().alias("report_rc_down_count"),
    )
    return grouped.with_columns(
        pl.when(pl.col("report_rc_sample_size") >= 5)
        .then(
            (pl.col("report_rc_up_count") - pl.col("report_rc_down_count"))
            / pl.col("report_rc_sample_size")
            * 100.0
        )
        .otherwise(None)
        .alias("report_rc_revision_ratio")
    )
