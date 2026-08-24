"""行业结构原始日频面板归一化。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.pipelines.industry_structure.classifier import IndustryClassifier
from stock_analytics.pipelines.industry_structure.panel_sources import optional_text_expr
from stock_core.contracts import MarketDataCatalog

if TYPE_CHECKING:
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig


def _panel_start_date(
    config: IndustryStructureConfig,
    as_of_date: date,
    trade_dates: tuple[date, ...],
) -> date:
    if trade_dates:
        return trade_dates[0] - timedelta(days=30)
    return as_of_date - timedelta(days=max(config.windows, default=config.main_window) * 4)


def _industry_daily_frame(
    frame: pl.DataFrame,
    config: IndustryStructureConfig,
    catalog: MarketDataCatalog,
) -> pl.DataFrame:
    required = {"symbol", "trade_date", "close"}
    if frame.is_empty() or not required.issubset(frame.columns):
        return pl.DataFrame()
    amount_expr = (
        pl.col("amount").cast(pl.Float64, strict=False)
        if "amount" in frame.columns
        else pl.lit(None, dtype=pl.Float64)
    )
    has_explicit_scope = {"classification", "industry_level"}.issubset(frame.columns)
    select_exprs = [
        pl.col("symbol").cast(pl.String).alias("industry_code"),
        "trade_date",
        optional_text_expr(frame, ("name", "industry_name", "index_name"), "_sw_industry_name"),
        pl.col("close").cast(pl.Float64, strict=False).alias("close"),
        amount_expr.alias("amount"),
    ]
    if has_explicit_scope:
        select_exprs.extend(
            [
                pl.col("classification").cast(pl.String, strict=False).alias("classification"),
                pl.col("industry_level").cast(pl.String, strict=False).alias("industry_level"),
            ]
        )
    base = frame.select(select_exprs).drop_nulls(subset=["industry_code", "trade_date", "close"])
    base = base.filter(pl.col("close") > 0).sort(["industry_code", "trade_date"])
    classifier = IndustryClassifier(catalog)
    if has_explicit_scope:
        base = base.filter(
            (pl.col("classification") == config.classification) & (pl.col("industry_level") == "L1")
        )
    else:
        l1_codes = list(classifier.get_l1_codes(config.classification))
        if l1_codes:
            l1_frame = base.filter(pl.col("industry_code").is_in(l1_codes))
            if l1_frame["industry_code"].n_unique() >= 10:
                base = l1_frame
    name_map = classifier.get_name_map(config.classification)
    return base.with_columns(
        pl.struct(["industry_code", "_sw_industry_name"])
        .map_elements(
            lambda row: _resolve_industry_name(
                str(row["industry_code"]),
                name_map,
                fallback=row.get("_sw_industry_name"),
            ),
            return_dtype=pl.Utf8,
        )
        .alias("industry_name")
    ).drop("_sw_industry_name")


def _resolve_industry_name(code: str, name_map: dict[str, str], *, fallback: object = None) -> str:
    if code in name_map:
        return name_map[code]
    prefix = code.split(".")[0]
    name = name_map.get(prefix)
    if name:
        return name
    fallback_text = str(fallback).strip() if fallback is not None else ""
    return fallback_text if fallback_text and fallback_text != "None" else code


def _coalesce_industry_names(panel: pl.DataFrame) -> pl.DataFrame:
    if "industry_name_from_valuation" not in panel.columns:
        return panel
    return panel.with_columns(
        pl.coalesce(
            pl.col("industry_name"),
            pl.col("industry_name_from_valuation"),
            pl.col("industry_code"),
        ).alias("industry_name")
    ).drop("industry_name_from_valuation")
