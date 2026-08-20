"""行业估值与财报面板的批次计算。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.industry_structure.panel_metrics import (
    as_float,
    collapse_industry_daily_values,
    historical_percentile,
)
from stock_analytics.pipelines.industry_structure.panel_sources import (
    load_dataset,
    load_financial_statement_history,
    map_l1_code,
    optional_numeric_expr,
    optional_text_expr,
)
from stock_analytics.pipelines.industry_structure.pb_roe import IndustryPBROEAnalyzer

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog


def valuation_panel_batch(
    cat: MarketDataCatalog,
    as_of_dates: tuple[date, ...],
    industry_to_l1: dict[str, str],
    *,
    classification_catalog: MarketDataCatalog | None = None,
) -> dict[date, pl.DataFrame]:
    """批量构建估值面板，避免每个基准日重复读取和归一整张估值表。"""
    if not as_of_dates:
        return {}
    raw = load_dataset(
        cat,
        "sw_2021_fundamental",
        start_date=min(as_of_dates) - timedelta(days=365 * 5),
        end_date=max(as_of_dates),
        columns=[
            "symbol",
            "trade_date",
            "name",
            "industry_name",
            "pe_ttm.ew",
            "pe_ttm.mcw",
            "pe_ttm",
            "pe",
            "pe_ew",
            "pb.ew",
            "pb.mcw",
            "pb",
            "pb_ew",
            "dyr.ew",
            "dyr.mcw",
            "dividend_yield",
            "dv_ttm",
        ],
    )
    if raw.is_empty() or not {"symbol", "trade_date"}.issubset(raw.columns):
        return {}
    base = _valuation_base_frame(raw, industry_to_l1)
    if base.is_empty():
        return {}
    raw_by_date = _partition_by_date(raw, "trade_date")
    analyzer = IndustryPBROEAnalyzer(
        catalog=cat,
        classifier_catalog=classification_catalog,
    )
    results: dict[date, pl.DataFrame] = {}
    for as_of_date in as_of_dates:
        history = base.filter(
            (pl.col("trade_date") >= as_of_date - timedelta(days=365 * 5))
            & (pl.col("trade_date") <= as_of_date)
        ).sort(["industry_code", "trade_date"])
        if history.is_empty():
            continue
        latest = history.group_by("industry_code").tail(1)
        eval_date = history["trade_date"].max()
        if not isinstance(eval_date, date):
            continue
        pbroe_by_l1 = _pb_roe_by_l1_frame(
            raw_by_date.get(eval_date, pl.DataFrame()),
            analyzer,
            industry_to_l1,
        )
        rows: list[dict[str, Any]] = []
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
            pbroe = pbroe_by_l1.get(code, {})
            row["pbroe_residual"] = as_float(pbroe.get("residual"))
            row["pbroe_undervalued"] = bool(pbroe.get("is_undervalued", False))
            rows.append(row)
        results[as_of_date] = pl.DataFrame(rows).select(
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
    return results


def fundamental_panel_batch(
    cat: MarketDataCatalog,
    as_of_dates: tuple[date, ...],
    industry_to_l1: dict[str, str],
) -> dict[date, pl.DataFrame]:
    """批量构建财报面板，按基准日切片已归一的历史序列。"""
    if not as_of_dates:
        return {}
    frame = load_financial_statement_history(
        cat,
        max(as_of_dates),
        start_date=min(as_of_dates) - timedelta(days=365 * 6),
    )
    if frame.is_empty():
        return {}
    frame = frame.with_columns(
        pl.col("industry_code")
        .map_elements(lambda value: map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code")
    ).drop_nulls(subset=["industry_code"])
    frame = collapse_industry_daily_values(
        frame,
        ("revenue_growth_ttm", "profit_growth_ttm", "roe_ttm"),
    )
    results: dict[date, pl.DataFrame] = {}
    for as_of_date in as_of_dates:
        history = frame.filter(
            (pl.col("trade_date") >= as_of_date - timedelta(days=365 * 6))
            & (pl.col("trade_date") <= as_of_date)
        ).sort(["industry_code", "trade_date"])
        if history.is_empty():
            continue
        latest = history.group_by("industry_code").tail(1)
        rows: list[dict[str, Any]] = []
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
        results[as_of_date] = pl.DataFrame(rows).select(
            "industry_code",
            "fundamental_date",
            "revenue_growth_ttm",
            "profit_growth_ttm",
            "roe_ttm",
            "revenue_growth_percentile",
            "profit_growth_percentile",
            "roe_percentile",
        )
    return results


def _valuation_base_frame(
    raw: pl.DataFrame,
    industry_to_l1: dict[str, str],
) -> pl.DataFrame:
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
    return collapse_industry_daily_values(base, ("pe_ttm", "pb", "dividend_yield"))


def _partition_by_date(frame: pl.DataFrame, date_column: str) -> dict[date, pl.DataFrame]:
    if frame.is_empty() or date_column not in frame.columns:
        return {}
    result: dict[date, pl.DataFrame] = {}
    for raw_key, partition in frame.partition_by(date_column, as_dict=True).items():
        key = raw_key[0] if isinstance(raw_key, tuple) else raw_key
        if isinstance(key, date):
            result[key] = partition
    return result


def _pb_roe_by_l1_frame(
    frame: pl.DataFrame,
    analyzer: IndustryPBROEAnalyzer,
    industry_to_l1: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if frame.is_empty():
        return {}
    try:
        result = analyzer.analyze_cross_section(val_df=frame)
    except Exception:
        return {}
    if result is None:
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for row in result.industries:
        l1_code = map_l1_code(row.get("symbol"), industry_to_l1)
        if l1_code:
            mapped[l1_code] = row
    return mapped
