"""行业结构分析面板基本面快报与资金流横截面聚合。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, cast

import polars as pl

from stock_analytics.pipelines.industry_structure.panel_sources import (
    date_column_expr,
    load_dataset,
    load_moneyflow_base_frame,
    load_stock_amount_frame,
    load_stock_industry_map,
    optional_numeric_expr,
    optional_text_expr,
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
) -> pl.DataFrame:
    """聚合预告、快报与研报上修的快速确认基本面指标。"""
    codes = [str(value) for value in context.industry_codes if value is not None]
    if not codes:
        return pl.DataFrame()
    stock_map = load_stock_industry_map(cat_ts, cat_lx, context.config, context.as_of_date)
    if stock_map.is_empty():
        return pl.DataFrame({"industry_code": codes})
    if len(context.trade_dates) >= context.config.main_window:
        window_start = context.trade_dates[-context.config.main_window]
    else:
        window_start = context.trade_dates[0]
    target_period = _latest_completed_report_period(context.as_of_date)
    panel = pl.DataFrame({"industry_code": codes})
    for frame in (
        _forecast_panel(cat_ts, stock_map, window_start, context.as_of_date, target_period),
        _express_panel(cat_ts, stock_map, window_start, context.as_of_date, target_period),
        _report_revision_panel(cat_ts, stock_map, window_start, context.as_of_date),
    ):
        if not frame.is_empty():
            panel = panel.join(frame, on="industry_code", how="left")
    return panel


def industry_moneyflow_panel(
    cat_ts: MarketDataCatalog,
    cat_lx: MarketDataCatalog,
    context: IndustryMoneyflowContext,
) -> pl.DataFrame:
    """聚合行业个股资金流净流入与占比指标。"""
    config = context.config
    as_of_date = context.as_of_date
    trade_dates = context.trade_dates
    industry_codes = context.industry_codes
    codes = [str(value) for value in industry_codes if value is not None]
    if not codes or not trade_dates:
        return pl.DataFrame()
    stock_map = load_stock_industry_map(cat_ts, cat_lx, config, as_of_date)
    if stock_map.is_empty():
        return pl.DataFrame({"industry_code": codes})
    window_dates = trade_dates[-config.main_window :]
    window_start = window_dates[0]
    flow = load_moneyflow_base_frame(cat_ts, window_start, as_of_date)
    if flow.is_empty():
        return pl.DataFrame({"industry_code": codes})
    bars = load_stock_amount_frame(cat_ts, window_start, as_of_date)
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
) -> pl.DataFrame:
    raw = load_dataset(catalog, "forecast")
    if raw.is_empty() or not {"symbol", "ann_date"}.issubset(raw.columns):
        return pl.DataFrame()
    positive_labels = ("预增", "略增", "续盈", "扭亏")
    base = raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        date_column_expr(raw, "ann_date", "ann_date"),
        date_column_expr(raw, "end_date", "end_date"),
        optional_text_expr(raw, ("type",), "type"),
        optional_numeric_expr(raw, ("p_change_min",), "p_change_min"),
        optional_numeric_expr(raw, ("p_change_max",), "p_change_max"),
    ).drop_nulls(subset=["stock_key", "ann_date"])
    base = base.filter((pl.col("ann_date") >= window_start) & (pl.col("ann_date") <= as_of_date))
    base = _filter_target_period_if_available(base, "end_date", target_period)
    if base.is_empty():
        return pl.DataFrame()
    base = base.with_columns(_midpoint_expr("p_change_min", "p_change_max").alias("_p_change_mid"))
    base = base.with_columns(
        pl.when(pl.col("_p_change_mid").is_not_null())
        .then((pl.col("_p_change_mid") > 0).cast(pl.Int64))
        .otherwise(pl.col("type").is_in(positive_labels).cast(pl.Int64))
        .alias("_positive")
    )
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
) -> pl.DataFrame:
    raw = load_dataset(catalog, "express")
    if raw.is_empty() or not {"symbol", "ann_date"}.issubset(raw.columns):
        return pl.DataFrame()
    base = raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        date_column_expr(raw, "ann_date", "ann_date"),
        date_column_expr(raw, "end_date", "end_date"),
        optional_numeric_expr(raw, ("n_income",), "n_income"),
        optional_numeric_expr(raw, ("yoy_net_profit",), "_prior_net_profit"),
        optional_numeric_expr(raw, ("diluted_roe",), "diluted_roe"),
    ).drop_nulls(subset=["stock_key", "ann_date"])
    base = base.filter((pl.col("ann_date") >= window_start) & (pl.col("ann_date") <= as_of_date))
    base = _filter_target_period_if_available(base, "end_date", target_period)
    if base.is_empty():
        return pl.DataFrame()
    base = base.with_columns(
        pl.when(pl.col("n_income").is_not_null() & (pl.col("_prior_net_profit") > 0))
        .then((pl.col("n_income") / pl.col("_prior_net_profit") - 1.0) * 100.0)
        .otherwise(None)
        .alias("_profit_growth")
    )
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
) -> pl.DataFrame:
    raw = load_dataset(catalog, "report_rc")
    required = {"symbol", "report_date", "org_name", "quarter", "np"}
    if raw.is_empty() or not required.issubset(raw.columns):
        return pl.DataFrame()
    base = raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        date_column_expr(raw, "report_date", "report_date"),
        pl.col("org_name").cast(pl.String).alias("org_name"),
        pl.col("quarter").cast(pl.String).alias("quarter"),
        pl.col("np").cast(pl.Float64, strict=False).alias("np"),
    ).drop_nulls(subset=["stock_key", "report_date", "org_name", "quarter", "np"])
    base = base.filter(pl.col("report_date") <= as_of_date).sort(
        ["stock_key", "org_name", "quarter", "report_date"]
    )
    if base.is_empty():
        return pl.DataFrame()
    base = base.with_columns(
        pl.col("np").shift(1).over(["stock_key", "org_name", "quarter"]).alias("_prev_np")
    )
    window = base.filter(pl.col("report_date") >= window_start).drop_nulls(subset=["_prev_np"])
    if window.is_empty():
        return pl.DataFrame()
    window = window.with_columns(
        (pl.col("np") > pl.col("_prev_np")).cast(pl.Int64).alias("_up"),
        (pl.col("np") < pl.col("_prev_np")).cast(pl.Int64).alias("_down"),
    )
    revisions = window.filter((pl.col("_up") + pl.col("_down")) > 0)
    joined = revisions.join(stock_map, on="stock_key", how="inner")
    if joined.is_empty():
        return pl.DataFrame()
    grouped = joined.group_by("industry_code").agg(
        pl.col("report_date").max().alias("report_rc_date"),
        pl.len().alias("report_rc_sample_size"),
        pl.col("_up").sum().alias("report_rc_up_count"),
        pl.col("_down").sum().alias("report_rc_down_count"),
    )
    return grouped.with_columns(
        pl.when((pl.col("report_rc_up_count") + pl.col("report_rc_down_count")) > 0)
        .then(
            pl.col("report_rc_up_count")
            / (pl.col("report_rc_up_count") + pl.col("report_rc_down_count"))
            * 100.0
        )
        .otherwise(None)
        .alias("report_rc_revision_ratio")
    )


def _filter_target_period_if_available(
    frame: pl.DataFrame,
    period_column: str,
    target_period: date,
) -> pl.DataFrame:
    if frame.is_empty() or period_column not in frame.columns:
        return frame
    target_rows = frame.filter(pl.col(period_column) == target_period)
    return target_rows if not target_rows.is_empty() else frame


def _latest_completed_report_period(as_of_date: date) -> date:
    year = as_of_date.year
    if as_of_date.month >= 10:
        return date(year, 9, 30)
    if as_of_date.month >= 7:
        return date(year, 6, 30)
    if as_of_date.month >= 4:
        return date(year, 3, 31)
    return date(year - 1, 12, 31)


def _midpoint_expr(left: str, right: str) -> pl.Expr:
    return (
        pl.when(pl.col(left).is_not_null() & pl.col(right).is_not_null())
        .then((pl.col(left) + pl.col(right)) / 2.0)
        .otherwise(pl.coalesce(pl.col(left), pl.col(right)))
    )
