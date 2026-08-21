"""个股排雷二次评分因子提取：从 sources 构建因子宽表。"""

from __future__ import annotations

from datetime import date

import polars as pl

from stock_analytics.pipelines.stock_screen.sources import (
    StockScreenSources,
    build_industry_map,
)


def build_factor_table(
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
    ocf = _compute_ocf_ratio(sources, symbols)
    goodwill = _goodwill_ratio(sources, symbols)

    result = passed.select("symbol", "name", "industry")
    for table in (daily, mom, fin, roe, ocf, goodwill):
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
    """从 stock_daily_bar 计算相对沪深300 的 20/60 日相对强弱。"""
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

    bench = _benchmark_returns(sources, as_of_date)
    if bench.is_empty():
        return result.rename({"return_20d": "rel_return_20d", "return_60d": "rel_return_60d"})
    return result.select(
        "symbol",
        (pl.col("return_20d") - bench.get_column("bench_return_20d").first()).alias(
            "rel_return_20d"
        ),
        (pl.col("return_60d") - bench.get_column("bench_return_60d").first()).alias(
            "rel_return_60d"
        ),
    )


def _benchmark_returns(sources: StockScreenSources, as_of_date: date) -> pl.DataFrame:
    """计算沪深300 指数 20/60 日涨幅，作为相对强弱基准（单行返回）。"""
    frame = sources.get("index_daily_bar")
    if frame.is_empty() or "trade_date" not in frame.columns or "symbol" not in frame.columns:
        return pl.DataFrame()
    clipped = frame.filter(pl.col("trade_date") <= pl.lit(as_of_date)).sort(
        "trade_date", descending=True
    )
    latest = clipped.group_by("symbol", maintain_order=True).agg(pl.col("close").first())
    prev_20 = clipped.group_by("symbol", maintain_order=True).agg(
        pl.col("close").slice(19, 1).first()
    )
    prev_60 = clipped.group_by("symbol", maintain_order=True).agg(
        pl.col("close").slice(59, 1).first()
    )
    result = (
        latest.select("symbol", pl.col("close").alias("now"))
        .join(prev_20.select("symbol", pl.col("close").alias("p20")), on="symbol", how="left")
        .join(prev_60.select("symbol", pl.col("close").alias("p60")), on="symbol", how="left")
        .filter(pl.col("now").is_not_null())
        .select(
            ((pl.col("now") / pl.col("p20") - 1) * 100).alias("bench_return_20d"),
            ((pl.col("now") / pl.col("p60") - 1) * 100).alias("bench_return_60d"),
        )
        .head(1)
    )
    if result.height == 0:
        return pl.DataFrame()
    return result


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


def _compute_ocf_ratio(sources: StockScreenSources, symbols: pl.DataFrame) -> pl.DataFrame:
    """计算净利润含金量 = 经营现金流 / 净利润。"""
    cashflow = sources.get("cashflow")
    income = sources.get("income")
    if cashflow.is_empty() or income.is_empty():
        return pl.DataFrame()
    if "n_cashflow_act" not in cashflow.columns or "ann_date" not in cashflow.columns:
        return pl.DataFrame()

    latest_cashflow = (
        cashflow.sort("ann_date", descending=True)
        .unique(subset=["symbol"], keep="first")
        .join(symbols, on="symbol", how="inner")
        .select(
            "symbol",
            pl.col("n_cashflow_act").cast(pl.Float64, strict=False).alias("n_cashflow_act"),
        )
    )
    latest_income = (
        income.sort("ann_date", descending=True)
        .unique(subset=["symbol"], keep="first")
        .join(symbols, on="symbol", how="inner")
        .select("symbol", pl.col("n_income").cast(pl.Float64, strict=False))
    )
    result = latest_cashflow.join(latest_income, on="symbol", how="left").select(
        "symbol",
        (pl.col("n_cashflow_act") / pl.col("n_income").abs().clip(1e-8, None)).alias("ocf_ratio"),
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


__all__ = ["build_factor_table"]
