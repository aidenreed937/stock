"""个股排雷二次评分：对通过标的按多因子综合评分排名。"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from stock_analytics.pipelines.stock_screen.factors import build_factor_table
from stock_analytics.pipelines.stock_screen.sources import StockScreenSources

MIN_INDUSTRY_SIZE = 30
_PCT_DEFAULT = 50.0

_SCORE_DIMENSIONS: list[dict[str, Any]] = [
    {
        "name": "quality",
        "weight": 0.40,
        "factors": [
            {"column": "roe", "inverse": False, "label": "ROE", "weight": 0.375},
            {"column": "netprofit_growth", "inverse": False, "label": "净利润增速", "weight": 0.25},
            {"column": "ocf_ratio", "inverse": False, "label": "经营现金流/净利润", "weight": 0.25},
            {"column": "goodwill_ratio", "inverse": True, "label": "商誉/净资产", "weight": 0.125},
        ],
    },
    {
        "name": "value",
        "weight": 0.30,
        "factors": [
            {"column": "pe", "inverse": True, "label": "PE", "weight": 0.5},
            {"column": "pb", "inverse": True, "label": "PB", "weight": 0.5},
        ],
    },
    {
        "name": "momentum",
        "weight": 0.20,
        "factors": [
            {"column": "rel_return_20d", "inverse": False, "label": "20日相对强弱", "weight": 0.4},
            {"column": "rel_return_60d", "inverse": False, "label": "60日相对强弱", "weight": 0.6},
        ],
    },
    {
        "name": "size",
        "weight": 0.10,
        "factors": [
            {"column": "total_mv", "inverse": False, "label": "总市值", "weight": 1.0},
        ],
    },
]


def compute_scores(
    passed: pl.DataFrame,
    sources: StockScreenSources,
    as_of_date: date,
) -> pl.DataFrame:
    """对通过标的计算多因子综合评分，返回带排名的 DataFrame。"""
    if passed.is_empty():
        return pl.DataFrame(schema=_output_schema())

    factors = build_factor_table(passed, sources, as_of_date)
    scored = _compute_percentile_scores(factors)
    scored = _compute_composite(scored)
    scored = scored.sort("composite_score", descending=True).with_columns(
        pl.int_range(1, pl.len() + 1).alias("rank")
    )
    return _align_columns(scored)


def _align_columns(scored: pl.DataFrame) -> pl.DataFrame:
    """按输出契约补齐缺失列，保证列结构与 _output_schema 一致。"""
    expressions = []
    for column, dtype in _output_schema().items():
        if column in scored.columns:
            expressions.append(pl.col(column).cast(dtype, strict=False))
        else:
            expressions.append(pl.lit(None, dtype=dtype).alias(column))
    return scored.select(expressions)


def _compute_percentile_scores(factors: pl.DataFrame) -> pl.DataFrame:
    """对每个因子列计算百分位排名（0-100），缺失值取中位数 50。"""
    base_cols = ["symbol", "name", "industry"]
    for col in ("l1_name", "l2_name"):
        if col in factors.columns:
            base_cols.append(col)
    work = factors.select(base_cols)

    for dim in _SCORE_DIMENSIONS:
        for factor in dim["factors"]:
            col = factor["column"]
            if col not in factors.columns:
                continue
            inverse = factor["inverse"]
            vals = _percentile_values(factors, col, inverse)
            series = pl.Series(f"score_{col}", vals, dtype=pl.Float64)
            work = work.with_columns(series)

    for dim in _SCORE_DIMENSIONS:
        present = [f for f in dim["factors"] if f"score_{f['column']}" in work.columns]
        if not present:
            continue
        total_weight = sum(float(f.get("weight", 1.0)) for f in present)
        exprs: list[pl.Expr] = [
            pl.col(f"score_{f['column']}").fill_null(50.0)
            * (float(f.get("weight", 1.0)) / total_weight)
            for f in present
        ]
        expr = pl.sum_horizontal(*exprs)
        work = work.with_columns(expr.alias(f"dim_{dim['name']}"))

    return work


def _percentile_values(frame: pl.DataFrame, column: str, inverse: bool = False) -> list[float]:
    """计算百分位排名值（0-100），按 L2→L1→全市场 分层回退。"""
    if column not in frame.columns:
        return [_PCT_DEFAULT] * frame.height
    n_all = frame.filter(pl.col(column).is_not_null() & pl.col(column).is_finite()).height
    if n_all <= 1:
        return [_PCT_DEFAULT] * frame.height

    col = pl.col(column)
    all_pct = (col.rank("min") - 1) / (n_all - 1) * 100

    if "l2_name" in frame.columns and "l1_name" in frame.columns:
        l2_size = pl.len().over("l2_name").clip(2, None)
        l1_size = pl.len().over("l1_name").clip(2, None)
        l2_pct = (col.rank("min").over("l2_name") - 1) / (l2_size - 1) * 100
        l1_pct = (col.rank("min").over("l1_name") - 1) / (l1_size - 1) * 100
        pct = (
            pl.when(l2_size >= MIN_INDUSTRY_SIZE)
            .then(l2_pct)
            .when(l1_size >= MIN_INDUSTRY_SIZE)
            .then(l1_pct)
            .otherwise(all_pct)
        )
    else:
        pct = all_pct

    if inverse:
        pct = 100 - pct
    pct = (
        pl.when(col.is_null() | col.is_finite().not_()).then(_PCT_DEFAULT).otherwise(pct)
    ).fill_null(_PCT_DEFAULT)

    evaluated = frame.select(pct.alias("pct"))
    return [float(v) for v in evaluated.get_column("pct").to_list()]


def _compute_composite(scored: pl.DataFrame) -> pl.DataFrame:
    """加权 composite_score。"""
    dim_cols = [f"dim_{d['name']}" for d in _SCORE_DIMENSIONS]
    available = [c for c in dim_cols if c in scored.columns]
    if not available:
        return scored.with_columns(pl.lit(50.0).alias("composite_score"))

    weight_map = {f"dim_{d['name']}": d["weight"] for d in _SCORE_DIMENSIONS}
    total_weight = sum(weight_map[c] for c in available)
    if total_weight <= 0:
        return scored.with_columns(pl.lit(50.0).alias("composite_score"))

    expr = sum(pl.col(c).fill_null(50.0) * (weight_map[c] / total_weight) for c in available)
    return scored.with_columns(expr.alias("composite_score"))


def _output_schema() -> dict[str, Any]:
    schema: dict[str, Any] = {
        "symbol": pl.String,
        "name": pl.String,
        "industry": pl.String,
        "l1_name": pl.String,
        "l2_name": pl.String,
    }
    for dim in _SCORE_DIMENSIONS:
        for factor in dim["factors"]:
            schema[f"score_{factor['column']}"] = pl.Float64
        schema[f"dim_{dim['name']}"] = pl.Float64
    schema["composite_score"] = pl.Float64
    schema["rank"] = pl.Int64
    return schema


__all__ = ["compute_scores"]
