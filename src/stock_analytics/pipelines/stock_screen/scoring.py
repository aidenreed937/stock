"""个股排雷二次评分：对通过标的按多因子综合评分排名。"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from stock_analytics.pipelines.stock_screen.sources import (
    StockScreenSources,
    build_industry_map,
)

MIN_INDUSTRY_SIZE = 30
_PCT_DEFAULT = 50.0

_SCORE_DIMENSIONS: list[dict[str, Any]] = [
    {
        "name": "quality",
        "weight": 0.35,
        "factors": [
            {"column": "roe", "inverse": False, "label": "ROE"},
            {"column": "netprofit_growth", "inverse": False, "label": "净利润增速"},
            {"column": "goodwill_ratio", "inverse": True, "label": "商誉占比"},
        ],
    },
    {
        "name": "value",
        "weight": 0.25,
        "factors": [
            {"column": "pe", "inverse": True, "label": "PE"},
            {"column": "pb", "inverse": True, "label": "PB"},
        ],
    },
    {
        "name": "momentum",
        "weight": 0.20,
        "factors": [
            {"column": "return_20d", "inverse": False, "label": "20日涨幅"},
            {"column": "return_60d", "inverse": False, "label": "60日涨幅"},
        ],
    },
    {
        "name": "liquidity",
        "weight": 0.15,
        "factors": [
            {"column": "avg_amount", "inverse": False, "label": "日均成交额"},
            {"column": "turnover_rate", "inverse": False, "label": "换手率"},
        ],
    },
    {
        "name": "size",
        "weight": 0.05,
        "factors": [
            {"column": "total_mv", "inverse": False, "label": "总市值"},
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

    factors = _build_factor_table(passed, sources, as_of_date)
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


def _build_factor_table(
    passed: pl.DataFrame,
    sources: StockScreenSources,
    as_of_date: date,
) -> pl.DataFrame:
    """从 sources 中提取因子值，宽表拼接。"""
    symbols = passed.select("symbol")

    daily = _latest_daily(sources, as_of_date, symbols)
    mom = _momentum(sources, as_of_date, symbols)
    fin = _latest_financial(sources, symbols)
    roe = _compute_roe(sources, symbols)
    goodwill = _goodwill_ratio(sources, symbols)

    result = passed.select("symbol", "name", "industry")
    for table in (daily, mom, fin, roe, goodwill):
        if not table.is_empty():
            result = result.join(table, on="symbol", how="left")

    industry_map = build_industry_map(sources, as_of_date)
    if not industry_map.is_empty():
        result = result.join(
            industry_map.select("symbol", "l2_name", "l1_name"),
            on="symbol",
            how="left",
        )
    return result


def _latest_daily(
    sources: StockScreenSources, as_of_date: date, symbols: pl.DataFrame
) -> pl.DataFrame:
    """取基准日当天的估值与市值数据。"""
    frame = sources.get("daily_basic")
    if frame.is_empty() or "trade_date" not in frame.columns:
        return pl.DataFrame()
    available = {"pe", "pb", "total_mv", "turnover_rate"} & set(frame.columns)
    if not available:
        return pl.DataFrame()
    select_exprs = [pl.col("symbol")]
    select_exprs += [pl.col(c).cast(pl.Float64, strict=False) for c in sorted(available)]
    result = (
        frame.filter(pl.col("trade_date") == pl.lit(as_of_date))
        .join(symbols, on="symbol", how="inner")
        .select(*select_exprs)
    )
    return result.with_columns(pl.col("symbol").cast(pl.String))


def _momentum(sources: StockScreenSources, as_of_date: date, symbols: pl.DataFrame) -> pl.DataFrame:
    """从 stock_daily_bar 计算 20 日和 60 日涨跌幅。"""
    frame = sources.get("stock_daily_bar")
    if frame.is_empty() or "trade_date" not in frame.columns:
        return pl.DataFrame()
    clipped = frame.filter(pl.col("trade_date") <= pl.lit(as_of_date)).join(
        symbols, on="symbol", how="inner"
    )
    if clipped.is_empty():
        return pl.DataFrame()

    sorted_bars = clipped.sort("trade_date", descending=True)
    latest = sorted_bars.group_by("symbol", maintain_order=True).agg(pl.col("close").first())

    prev_20 = sorted_bars.group_by("symbol", maintain_order=True).agg(
        pl.col("close").slice(19, 1).first()
    )
    prev_60 = sorted_bars.group_by("symbol", maintain_order=True).agg(
        pl.col("close").slice(59, 1).first()
    )

    result = latest.select("symbol", pl.col("close").alias("close_now"))
    if not prev_20.is_empty():
        result = result.join(
            prev_20.select("symbol", pl.col("close").alias("close_20d")),
            on="symbol",
            how="left",
        )
    if not prev_60.is_empty():
        result = result.join(
            prev_60.select("symbol", pl.col("close").alias("close_60d")),
            on="symbol",
            how="left",
        )
    result = result.select(
        "symbol",
        ((pl.col("close_now") / pl.col("close_20d") - 1) * 100).alias("return_20d"),
        ((pl.col("close_now") / pl.col("close_60d") - 1) * 100).alias("return_60d"),
    )
    return result.with_columns(pl.col("symbol").cast(pl.String))


def _latest_financial(sources: StockScreenSources, symbols: pl.DataFrame) -> pl.DataFrame:
    """取最新财务指标（净利润增速）。"""
    frame = sources.get("fina_indicator")
    if frame.is_empty() or "ann_date" not in frame.columns:
        return pl.DataFrame()
    result = (
        frame.sort("ann_date", descending=True)
        .unique(subset=["symbol"], keep="first")
        .join(symbols, on="symbol", how="inner")
        .select(
            "symbol",
            pl.col("netprofit_yoy").cast(pl.Float64, strict=False).alias("netprofit_growth"),
        )
    )
    return result.with_columns(pl.col("symbol").cast(pl.String))


def _compute_roe(sources: StockScreenSources, symbols: pl.DataFrame) -> pl.DataFrame:
    """计算 ROE = n_income / total_hldr_eqy_exc_min_int。"""
    income = sources.get("income")
    equity = sources.get("balancesheet")
    if income.is_empty() or equity.is_empty():
        return pl.DataFrame()

    latest_income = (
        income.sort("ann_date", descending=True)
        .unique(subset=["symbol"], keep="first")
        .join(symbols, on="symbol", how="inner")
        .select("symbol", pl.col("n_income").cast(pl.Float64, strict=False))
    )
    latest_equity = (
        equity.sort("ann_date", descending=True)
        .unique(subset=["symbol"], keep="first")
        .join(symbols, on="symbol", how="inner")
        .select("symbol", pl.col("total_hldr_eqy_exc_min_int").cast(pl.Float64, strict=False))
    )
    result = latest_income.join(latest_equity, on="symbol", how="left").select(
        "symbol",
        (
            pl.col("n_income") / pl.col("total_hldr_eqy_exc_min_int").abs().clip(1e-8, None) * 100
        ).alias("roe"),
    )
    return result.with_columns(pl.col("symbol").cast(pl.String))


def _goodwill_ratio(sources: StockScreenSources, symbols: pl.DataFrame) -> pl.DataFrame:
    """计算商誉占比 = goodwill / total_hldr_eqy_exc_min_int。"""
    frame = sources.get("balancesheet")
    if frame.is_empty() or "ann_date" not in frame.columns:
        return pl.DataFrame()
    result = (
        frame.sort("ann_date", descending=True)
        .unique(subset=["symbol"], keep="first")
        .join(symbols, on="symbol", how="inner")
        .select(
            "symbol",
            (
                pl.col("goodwill").cast(pl.Float64, strict=False)
                / pl.col("total_hldr_eqy_exc_min_int")
                .cast(pl.Float64, strict=False)
                .abs()
                .clip(1e-8, None)
                * 100
            ).alias("goodwill_ratio"),
        )
    )
    return result.with_columns(pl.col("symbol").cast(pl.String))


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
        cols = [
            f"score_{f['column']}" for f in dim["factors"] if f"score_{f['column']}" in work.columns
        ]
        if cols:
            factor_weight = 1.0 / len(cols)
            exprs: list[pl.Expr] = [pl.col(c).fill_null(50.0) * factor_weight for c in cols]
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


def _percentile_rank(frame: pl.DataFrame, column: str, inverse: bool = False) -> pl.Expr:
    """计算百分位排名（0-100）。"""
    valid = frame.filter(pl.col(column).is_not_null() & pl.col(column).is_finite())
    if valid.is_empty():
        return pl.lit(50.0)
    count = valid.height
    if count <= 1:
        return pl.lit(50.0)

    if inverse:
        expr = (1 - (pl.col(column).rank("min") - 1) / (count - 1)) * 100
    else:
        expr = (pl.col(column).rank("min") - 1) / (count - 1) * 100
    return expr


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
