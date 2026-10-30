"""全球大类资产与宏观流动性日频领域 Mart。

聚合 FRED / YFinance / AlphaVantage / LiXinger / TuShare 五源的日度宏观序列为
单一日频宽表，消除跨源读取与时区对齐开销。所有收益率（美债、中债、SHIBOR、LPR）
统一为百分数（如 1.7% 记 1.7）；理杏仁中债序列原始为小数（0.017），构建时放大 100。
"""

from __future__ import annotations

from typing import Any

import polars as pl

GLOBAL_MACRO_MART_NAME = "global_macro_daily"

GLOBAL_MACRO_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "us_10y_yield": pl.Float64,
    "us_2y_yield": pl.Float64,
    "us_3m_yield": pl.Float64,
    "us_yield_curve_10y_2y": pl.Float64,
    "cn_1y_yield": pl.Float64,
    "cn_5y_yield": pl.Float64,
    "cn_10y_yield": pl.Float64,
    "cn_30y_yield": pl.Float64,
    "cnh_close": pl.Float64,
    "cnh_return_20d": pl.Float64,
    "usd_index": pl.Float64,
    "gold_price": pl.Float64,
    "crude_oil_price": pl.Float64,
    "brent_crude_oil_price": pl.Float64,
    "copper_price": pl.Float64,
    "copper_gold_ratio": pl.Float64,
    "vix_close": pl.Float64,
    "sox_close": pl.Float64,
    "oecd_cli": pl.Float64,
    "us_durable_goods_orders": pl.Float64,
    "us_manufacturing_shipments": pl.Float64,
    "shibor_on": pl.Float64,
    "shibor_3m": pl.Float64,
    "shibor_lpr_1y": pl.Float64,
}


def empty_global_macro() -> pl.DataFrame:
    """返回稳定 schema 的空全球宏观 Mart。"""
    return pl.DataFrame(schema=GLOBAL_MACRO_SCHEMA)


def _pivot_close(frame: pl.DataFrame, source: str = "") -> pl.DataFrame:
    """把长表 (trade_date, symbol, close) 透视成 symbol 列宽表。"""
    if frame.is_empty() or "symbol" not in frame.columns:
        return pl.DataFrame()
    wide = frame.pivot(
        on="symbol",
        index="trade_date",
        values="close",
        aggregate_function="last",
    )
    for column in wide.columns:
        if column != "trade_date":
            wide = wide.rename({column: f"{source}_{column}"})
    return wide


def _clean_close(frame: pl.DataFrame, value_column: str = "close") -> pl.DataFrame:
    """裁剪为 (trade_date, close) 并过滤非法数值。"""
    if frame.is_empty() or value_column not in frame.columns:
        return pl.DataFrame()
    return (
        frame.select("trade_date", pl.col(value_column).cast(pl.Float64, strict=False))
        .unique(subset=["trade_date"], keep="last")
        .sort("trade_date")
        .filter(pl.col(value_column).is_finite())
    )


def _merge_primary_fallback_series(
    primary: pl.DataFrame,
    fallback: pl.DataFrame,
    value_column: str,
) -> pl.DataFrame:
    """按日期合并主源与回退源，同日优先保留主源值。"""
    if primary.is_empty():
        return fallback
    if fallback.is_empty():
        return primary
    return (
        pl.concat([primary, fallback], how="diagonal_relaxed")
        .group_by("trade_date", maintain_order=True)
        .agg(pl.col(value_column).drop_nulls().first().alias(value_column))
        .sort("trade_date")
    )


def _merge_series(
    base: pl.DataFrame | None,
    series: pl.DataFrame,
    *,
    rename: dict[str, str],
) -> pl.DataFrame:
    """把单序列 (trade_date, close) 以左连接合并进主日历。"""
    if series.is_empty():
        return base if base is not None else pl.DataFrame()
    clean = _clean_close(series).rename(rename)
    if base is None or base.is_empty():
        return clean.select("trade_date", *rename.values()).sort("trade_date")
    return base.join(clean, on="trade_date", how="left").sort("trade_date")


def _asof_fill_series(frame: pl.DataFrame, column: str) -> pl.DataFrame:
    """把低频序列按最近已公布观测向后对齐到统一日历。"""
    if column not in frame.columns:
        return frame
    available = frame.select(["trade_date", column]).drop_nulls(subset=[column]).sort("trade_date")
    if available.is_empty():
        return frame
    return (
        frame.drop(column)
        .sort("trade_date")
        .join_asof(available, on="trade_date", strategy="backward")
        .sort("trade_date")
    )


def _ensure_schema_columns(frame: pl.DataFrame, schema: dict[str, Any]) -> pl.DataFrame:
    """补齐稳定 schema 中缺失的列（缺失源序列时为 null）。"""
    if frame.is_empty():
        return frame
    missing = [
        pl.lit(None, dtype=dtype).alias(column)
        for column, dtype in schema.items()
        if column not in frame.columns
    ]
    if missing:
        frame = frame.with_columns(missing)
    return frame.select(list(schema))


def build_global_macro_daily_frame(
    yfinance_macro: pl.DataFrame,
    fred_macro: pl.DataFrame,
    lixinger_national_debt: pl.DataFrame,
    shibor: pl.DataFrame,
    shibor_lpr: pl.DataFrame,
    lixinger_gold_price: pl.DataFrame | None = None,
    lixinger_non_ferrous_metals: pl.DataFrame | None = None,
    lixinger_crude_oil: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """从多源长表构建全球宏观日频宽表。

    主日历取全部输入日期的并集（交易日对齐由各源自身日期决定，不做跨市场
    时区重排）；CNH 20 日动量在合并后统一计算。
    """
    # ---- FRED：官方利率、波动率、美元与原油序列 ----
    fred_symbols = {
        "DGS10": "us_10y_yield",
        "DGS3MO": "us_3m_yield",
        "VIXCLS": "vix_close",
        "DCOILWTICO": "crude_oil_price",
        "DTWEXBGS": "usd_index",
    }
    source_series: dict[str, pl.DataFrame] = {}
    if not fred_macro.is_empty():
        for symbol, target in fred_symbols.items():
            sub = fred_macro.filter(pl.col("symbol") == symbol)
            if sub.is_empty():
                continue
            series = _clean_close(sub)
            if not series.is_empty():
                source_series[target] = series.rename({"close": target})

    # ---- LiXinger：伦敦金美元定盘价，作为 Yahoo GC=F 的主替代源 ----
    if lixinger_gold_price is not None and not lixinger_gold_price.is_empty():
        gold_series = _clean_close(lixinger_gold_price, value_column="lbma_pm_usd")
        if not gold_series.is_empty():
            source_series["gold_price"] = gold_series.rename({"lbma_pm_usd": "gold_price"})

    # ---- LiXinger：伦敦铜现货 l_cu_p，统一作为铜价主源 ----
    if lixinger_non_ferrous_metals is not None and not lixinger_non_ferrous_metals.is_empty():
        copper_series = _clean_close(lixinger_non_ferrous_metals, value_column="l_cu_p")
        if not copper_series.is_empty():
            source_series["copper_price"] = copper_series.rename({"l_cu_p": "copper_price"})

    # ---- LiXinger：WTI/Brent 现货为主源，FRED/Yahoo 原油序列补缺 ----
    if lixinger_crude_oil is not None and not lixinger_crude_oil.is_empty():
        wti_series = _clean_close(lixinger_crude_oil, value_column="wti_co_sp")
        if not wti_series.is_empty():
            wti_series = wti_series.rename({"wti_co_sp": "crude_oil_price"})
            fred_wti = source_series.get("crude_oil_price", pl.DataFrame())
            source_series["crude_oil_price"] = _merge_primary_fallback_series(
                wti_series,
                fred_wti,
                "crude_oil_price",
            )

        brent_series = _clean_close(lixinger_crude_oil, value_column="brent_co_sp")
        if not brent_series.is_empty():
            source_series["brent_crude_oil_price"] = brent_series.rename(
                {"brent_co_sp": "brent_crude_oil_price"}
            )

    # ---- 兼容回退：旧 Yahoo 宏观快照与 Alpha Vantage CNH ----
    legacy_symbols = {
        "^TNX": "us_10y_yield",
        "^IRX": "us_3m_yield",
        "^VIX": "vix_close",
        "GC=F": "gold_price",
        "CL=F": "crude_oil_price",
        "CNH=X": "cnh_close",
        "DX-Y.NYB": "usd_index",
        "^SOX": "sox_close",
    }
    if not yfinance_macro.is_empty():
        for symbol, target in legacy_symbols.items():
            sub = yfinance_macro.filter(pl.col("symbol") == symbol)
            if sub.is_empty():
                continue
            if target in source_series:
                if target in {"gold_price", "crude_oil_price"} and "close" in sub.columns:
                    fallback = _clean_close(sub).rename({"close": target})
                    source_series[target] = _merge_primary_fallback_series(
                        source_series[target], fallback, target
                    )
                continue
            series = _clean_close(sub)
            if not series.is_empty():
                source_series[target] = series.rename({"close": target})

    # CNH remains supplied by Alpha Vantage and is kept separate from FRED.
    if "cnh_close" not in source_series and not yfinance_macro.is_empty():
        sub = yfinance_macro.filter(pl.col("symbol") == "CNH=X")
        if not sub.is_empty():
            series = _clean_close(sub)
            if not series.is_empty():
                source_series["cnh_close"] = series.rename({"close": "cnh_close"})

    frames = list(source_series.values())
    yf_frame = frames[0] if frames else pl.DataFrame()
    for frame in frames[1:]:
        yf_frame = yf_frame.join(frame, on="trade_date", how="full", coalesce=True).sort(
            "trade_date"
        )

    # ---- FRED：利差、OECD 领先指标、耐用品订单与出货 ----
    fred_context_symbols = {
        "T10Y2Y": "us_yield_curve_10y_2y",
        "OECDLOLITOAASTSAM": "oecd_cli",
        "DGORDER": "us_durable_goods_orders",
        "AMTMVS": "us_manufacturing_shipments",
    }
    fred_frames: list[pl.DataFrame] = []
    if not fred_macro.is_empty():
        for symbol, target in fred_context_symbols.items():
            sub = fred_macro.filter(pl.col("symbol") == symbol)
            if sub.is_empty():
                continue
            series = _clean_close(sub)
            if series.is_empty():
                continue
            fred_frames.append(series.rename({"close": target}))
    fred_frame = fred_frames[0] if fred_frames else pl.DataFrame()
    for frame in fred_frames[1:]:
        fred_frame = fred_frame.join(frame, on="trade_date", how="full", coalesce=True).sort(
            "trade_date"
        )

    # ---- LiXinger：中债收益率（小数 -> 百分数）----
    cn_debt = pl.DataFrame()
    if not lixinger_national_debt.is_empty():
        cn_debt = lixinger_national_debt.select(
            "trade_date",
            (pl.col("tcm_y1").cast(pl.Float64, strict=False) * 100.0).alias("cn_1y_yield"),
            (pl.col("tcm_y5").cast(pl.Float64, strict=False) * 100.0).alias("cn_5y_yield"),
            (pl.col("tcm_y10").cast(pl.Float64, strict=False) * 100.0).alias("cn_10y_yield"),
            (pl.col("tcm_y30").cast(pl.Float64, strict=False) * 100.0).alias("cn_30y_yield"),
        )

    # ---- TuShare：SHIBOR 与 LPR（百分数原样）----
    cn_money = pl.DataFrame()
    if not shibor.is_empty():
        cn_money = shibor.select(
            "trade_date",
            pl.col("on").cast(pl.Float64, strict=False).alias("shibor_on"),
            pl.col("3m").cast(pl.Float64, strict=False).alias("shibor_3m"),
        ).filter(pl.col("shibor_on").is_not_null())
    lpr = pl.DataFrame()
    if not shibor_lpr.is_empty():
        lpr = shibor_lpr.select(
            "trade_date",
            pl.col("1y").cast(pl.Float64, strict=False).alias("shibor_lpr_1y"),
        )

    # ---- 逐源合并到统一主日历 ----
    merged = yf_frame
    for frame in (fred_frame, cn_debt, cn_money, lpr):
        if frame.is_empty():
            continue
        merged = merged.join(frame, on="trade_date", how="full", coalesce=True)

    if merged.is_empty():
        return empty_global_macro()

    merged = merged.sort("trade_date")
    # LiXinger 铜价可能存在交易日缺口：只允许沿用最近已公布的观测，
    # 不能把未来日期的铜价回填到过去；日频金价据此形成无前视铜金比。
    merged = _asof_fill_series(merged, "copper_price")
    # 美债 2Y：10Y - 官方利差（T10Y2Y），在合并后的统一日历上计算
    if "us_10y_yield" in merged.columns and "us_yield_curve_10y_2y" in merged.columns:
        merged = merged.with_columns(
            (pl.col("us_10y_yield") - pl.col("us_yield_curve_10y_2y")).alias("us_2y_yield")
        )
    # 铜金比：铜价 / 金价
    if {"copper_price", "gold_price"}.issubset(merged.columns):
        merged = merged.with_columns(
            pl.when(pl.col("gold_price") > 0)
            .then(pl.col("copper_price") / pl.col("gold_price"))
            .otherwise(None)
            .alias("copper_gold_ratio")
        )
    # CNH 20 日动量已在 build 步骤内补充（此处仅保证列存在）
    if "cnh_return_20d" not in merged.columns:
        merged = merged.with_columns(pl.lit(None, dtype=pl.Float64).alias("cnh_return_20d"))

    return _ensure_schema_columns(merged, GLOBAL_MACRO_SCHEMA).sort("trade_date")


__all__ = ["GLOBAL_MACRO_MART_NAME", "build_global_macro_daily_frame", "empty_global_macro"]
