"""行业结构分析面板指标计算与因子聚合。"""

from __future__ import annotations

from datetime import date, timedelta
from math import isfinite
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.industry_structure.panel_sources import (
    load_dataset,
    load_financial_statement_history,
    map_l1_code,
    optional_numeric_expr,
    optional_text_expr,
)
from stock_analytics.pipelines.industry_structure.pb_roe import IndustryPBROEAnalyzer
from stock_analytics.primitives.rules import percentile_rank

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog


def with_return_columns(daily: pl.DataFrame, windows: tuple[int, ...]) -> pl.DataFrame:
    """计算各窗口收益率。"""
    expressions = [
        (
            (pl.col("close") / pl.col("close").shift(window).over("industry_code") - 1.0) * 100.0
        ).alias(f"return_{window}d")
        for window in windows
    ]
    return daily.with_columns(expressions)


def with_market_columns(daily: pl.DataFrame, main_window: int) -> pl.DataFrame:
    """计算均线乖离率与 TCR（成交占比滚动均值）。"""
    daily = daily.with_columns(
        pl.col("close").rolling_mean(main_window).over("industry_code").alias("_ma_main")
    )
    daily = daily.with_columns(
        pl.when(pl.col("_ma_main") > 0)
        .then((pl.col("close") / pl.col("_ma_main") - 1.0) * 100.0)
        .otherwise(None)
        .alias("ma_bias_20d"),
        pl.when(pl.col("amount").sum().over("trade_date") > 0)
        .then(pl.col("amount") / pl.col("amount").sum().over("trade_date") * 100.0)
        .otherwise(None)
        .alias("_amount_share"),
    )
    return daily.with_columns(
        pl.col("_amount_share").rolling_mean(main_window).over("industry_code").alias("tcr")
    ).drop("_ma_main", "_amount_share")


def valuation_panel(
    cat: MarketDataCatalog,
    as_of_date: date,
    industry_to_l1: dict[str, str],
) -> pl.DataFrame:
    """构建估值与 PB-ROE 残差特征面板。"""
    start_date = as_of_date - timedelta(days=365 * 5)
    raw = load_dataset(
        cat,
        "sw_2021_fundamental",
        start_date=start_date,
        end_date=as_of_date,
    )
    if raw.is_empty() or not {"symbol", "trade_date"}.issubset(raw.columns):
        return pl.DataFrame()
    base = raw.select(
        pl.col("symbol")
        .cast(pl.String)
        .map_elements(lambda value: map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code"),
        "trade_date",
        optional_text_expr(raw, ("name", "industry_name"), "industry_name_from_valuation"),
        optional_numeric_expr(
            raw,
            ("pe_ttm.ew", "pe_ttm.mcw", "pe_ttm", "pe", "pe_ew"),
            "pe_ttm",
        ),
        optional_numeric_expr(raw, ("pb.ew", "pb.mcw", "pb", "pb_ew"), "pb"),
        optional_numeric_expr(
            raw,
            ("dyr.ew", "dyr.mcw", "dividend_yield", "dv_ttm"),
            "dividend_yield",
        ),
    ).drop_nulls(subset=["industry_code", "trade_date"])
    base = collapse_industry_daily_values(
        base,
        ("pe_ttm", "pb", "dividend_yield"),
    )
    history = base.filter(pl.col("trade_date") <= as_of_date).sort(["industry_code", "trade_date"])
    if history.is_empty():
        return pl.DataFrame()
    latest = history.group_by("industry_code").tail(1)
    pbroe_by_symbol = _pb_roe_by_l1_symbol(raw, as_of_date, cat, industry_to_l1)
    rows = []
    for row in latest.to_dicts():
        code = str(row["industry_code"])
        industry_history = history.filter(pl.col("industry_code") == code)
        row["valuation_date"] = row["trade_date"]
        row["pe_percentile_5y"] = historical_percentile(
            industry_history["pe_ttm"].to_list(), as_float(row.get("pe_ttm"))
        )
        row["pb_percentile_5y"] = historical_percentile(
            industry_history["pb"].to_list(), as_float(row.get("pb"))
        )
        pbroe = pbroe_by_symbol.get(code, {})
        row["pbroe_residual"] = as_float(pbroe.get("residual"))
        row["pbroe_undervalued"] = bool(pbroe.get("is_undervalued", False))
        rows.append(row)
    return pl.DataFrame(rows).select(
        "industry_code",
        "industry_name_from_valuation",
        "valuation_date",
        "pe_ttm",
        "pb",
        "dividend_yield",
        "pe_percentile_5y",
        "pb_percentile_5y",
        "pbroe_residual",
        "pbroe_undervalued",
    )


def fundamental_panel(
    cat: MarketDataCatalog,
    as_of_date: date,
    industry_to_l1: dict[str, str],
) -> pl.DataFrame:
    """构建季频行业财报基础面板。"""
    frame = load_financial_statement_history(cat, as_of_date)
    if frame.is_empty():
        return pl.DataFrame()
    frame = frame.with_columns(
        pl.col("industry_code")
        .map_elements(lambda value: map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code")
    ).drop_nulls(subset=["industry_code"])
    frame = collapse_industry_daily_values(
        frame,
        ("revenue_growth_ttm", "profit_growth_ttm", "roe_ttm"),
    )
    history = frame.filter(pl.col("trade_date") <= as_of_date).sort(["industry_code", "trade_date"])
    if history.is_empty():
        return pl.DataFrame()
    latest = history.group_by("industry_code").tail(1)
    rows = []
    for row in latest.to_dicts():
        code = str(row["industry_code"])
        industry_history = history.filter(pl.col("industry_code") == code)
        row["fundamental_date"] = row["trade_date"]
        row["revenue_growth_percentile"] = historical_percentile(
            industry_history["revenue_growth_ttm"].to_list(),
            as_float(row.get("revenue_growth_ttm")),
        )
        row["profit_growth_percentile"] = historical_percentile(
            industry_history["profit_growth_ttm"].to_list(),
            as_float(row.get("profit_growth_ttm")),
        )
        row["roe_percentile"] = historical_percentile(
            industry_history["roe_ttm"].to_list(), as_float(row.get("roe_ttm"))
        )
        rows.append(row)
    return pl.DataFrame(rows).select(
        "industry_code",
        "fundamental_date",
        "revenue_growth_ttm",
        "profit_growth_ttm",
        "roe_ttm",
        "revenue_growth_percentile",
        "profit_growth_percentile",
        "roe_percentile",
    )


def collapse_industry_daily_values(
    frame: pl.DataFrame,
    numeric_columns: tuple[str, ...],
) -> pl.DataFrame:
    """对同一行业日期的多条记录取中位数合并。"""
    if frame.is_empty():
        return frame
    group_columns = {"industry_code", "trade_date"}
    expressions = [
        pl.col(column).median().alias(column)
        for column in numeric_columns
        if column in frame.columns
    ]
    expressions.extend(
        pl.col(column).drop_nulls().first().alias(column)
        for column in frame.columns
        if column not in group_columns and column not in numeric_columns
    )
    return frame.group_by(["industry_code", "trade_date"]).agg(expressions)


def historical_percentile(values: list[object], current: float | None) -> float | None:
    """计算当前值在历史序列中的分位数。"""
    if current is None:
        return None
    clean: list[float] = []
    for value in values:
        numeric = as_float(value)
        if numeric is not None and isfinite(numeric):
            clean.append(numeric)
    if len(clean) < 3:
        return None
    percentile = percentile_rank(pl.Series(clean), len(clean), current=current)
    return round(percentile, 2) if percentile is not None else None


def median_value(frame: pl.DataFrame, column: str) -> float | None:
    """计算列中位数。"""
    if frame.is_empty() or column not in frame.columns:
        return None
    value = frame.select(pl.col(column).median()).item()
    return as_float(value)


def as_float(value: object) -> float | None:
    """通用转浮点数安全辅助。"""
    if value is None:
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _pb_roe_by_symbol(
    raw: pl.DataFrame,
    as_of_date: date,
    catalog: MarketDataCatalog,
) -> dict[str, dict[str, Any]]:
    try:
        result = IndustryPBROEAnalyzer(catalog=catalog).analyze_cross_section(
            target_date=as_of_date,
            val_df=raw,
        )
    except Exception:
        return {}
    if result is None:
        return {}
    return {str(row["symbol"]): row for row in result.industries}


def _pb_roe_by_l1_symbol(
    raw: pl.DataFrame,
    as_of_date: date,
    catalog: MarketDataCatalog,
    industry_to_l1: dict[str, str],
) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for symbol, data in _pb_roe_by_symbol(raw, as_of_date, catalog).items():
        l1_code = map_l1_code(symbol, industry_to_l1)
        if l1_code:
            mapped[l1_code] = data
    return mapped
