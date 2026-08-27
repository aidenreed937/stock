"""申万二级行业估值与动量日频领域 Mart。

把理杏仁 ``sw_2021_l2_fundamental``（162 个申万二级行业估值）与 TuShare
``sw_daily`` L2 行情合并，输出 5/20/60 日动量与 5Y/10Y 滚动估值分位，
衔接一级行业 ``industry_daily`` 的下钻分析能力。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from stock_analytics.marts.shared.rolling_percentile import (
    WINDOW_5Y_DAYS,
    WINDOW_10Y_DAYS,
    add_rolling_percentiles,
)
from stock_analytics.primitives.units import YUAN_PER_YI

INDUSTRY_L2_MART_NAME = "industry_l2_daily"

RETURN_WINDOWS = (5, 20, 60)

PERCENTILE_VALUE_COLUMNS = ("pe_ttm_ew", "pb_ew", "dyr_ew", "mc")

INDUSTRY_L2_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "industry_code": pl.Utf8,
    "industry_name": pl.Utf8,
    "parent_l1_code": pl.Utf8,
    "parent_l1_name": pl.Utf8,
    "close": pl.Float64,
    "amount": pl.Float64,
    "amount_yi": pl.Float64,
    "return_5d": pl.Float64,
    "return_20d": pl.Float64,
    "return_60d": pl.Float64,
    "pe_ttm_ew": pl.Float64,
    "pb_ew": pl.Float64,
    "dyr_ew": pl.Float64,
    "mc": pl.Float64,
    "pe_ttm_ew_percentile_5y": pl.Float64,
    "pe_ttm_ew_percentile_10y": pl.Float64,
    "pb_ew_percentile_5y": pl.Float64,
    "pb_ew_percentile_10y": pl.Float64,
}


def empty_industry_l2() -> pl.DataFrame:
    """返回稳定 schema 的空申万二级行业 Mart。"""
    return pl.DataFrame(schema=INDUSTRY_L2_SCHEMA)


def build_industry_l2_frame(
    sw_daily: pl.DataFrame,
    l2_fundamental: pl.DataFrame,
    *,
    percentile_cutoff: date | None = None,
) -> pl.DataFrame:
    """合并申万二级行业行情与理杏仁估值，计算收益与分位。

    ``sw_daily`` 需要含 ``trade_date``、``industry_level``、``industry_code``
    （6 位数字码）、``parent_code``、``name``、``close``、``amount``；
    本函数内部按 ``industry_level == "L2"`` 过滤，并以 L1 行补齐父级行业名。
    ``l2_fundamental`` 需要含 ``symbol``（6 位数字码）、``trade_date`` 与理杏仁估值列。
    ``percentile_cutoff`` 传入时仅计算该日期及之后行（增量构建语义）。
    """
    if sw_daily.is_empty() or l2_fundamental.is_empty():
        return empty_industry_l2()

    sw_daily = sw_daily.with_columns(
        pl.col("industry_code").cast(pl.Utf8, strict=False),
        pl.col("parent_code").cast(pl.Utf8, strict=False),
    )
    sw_daily_l2 = sw_daily.filter(pl.col("industry_level") == "L2")

    # 一级行业码 -> 名称（选取 L1 行，按一级码去重防止 join 放量）
    l1_names = (
        sw_daily.filter(pl.col("industry_level") == "L1")
        .select(
            pl.col("industry_code").alias("parent_l1_code"),
            pl.col("name").alias("parent_l1_name"),
        )
        .unique(subset=["parent_l1_code"], keep="first")
    )

    market = sw_daily_l2.select(
        "trade_date",
        pl.col("industry_code").cast(pl.Utf8, strict=False).alias("industry_code"),
        pl.col("parent_code").cast(pl.Utf8, strict=False).alias("parent_l1_code"),
        pl.col("name").cast(pl.Utf8, strict=False).alias("industry_name"),
        pl.col("close").cast(pl.Float64, strict=False),
        pl.col("amount").cast(pl.Float64, strict=False),
    ).unique(subset=["trade_date", "industry_code"], keep="first")
    valuation = l2_fundamental.select(
        "trade_date",
        pl.col("symbol").cast(pl.Utf8, strict=False).alias("industry_code"),
        pl.col("pe_ttm.ew").cast(pl.Float64, strict=False).alias("pe_ttm_ew"),
        pl.col("pb.ew").cast(pl.Float64, strict=False).alias("pb_ew"),
        pl.col("dyr.ew").cast(pl.Float64, strict=False).alias("dyr_ew"),
        pl.col("mc").cast(pl.Float64, strict=False).alias("mc"),
    ).unique(subset=["trade_date", "industry_code"], keep="first")

    # 一级行业名映射：parent_l1_code -> name（取自 sw_daily L1 行）
    joined = market.join(valuation, on=["trade_date", "industry_code"], how="left")
    if not l1_names.is_empty():
        joined = joined.join(l1_names, on="parent_l1_code", how="left")

    if joined.is_empty():
        return empty_industry_l2()

    # 窗口收益率（%）
    joined = joined.sort(["industry_code", "trade_date"])
    joined = joined.with_columns(
        [
            (
                (pl.col("close") / pl.col("close").shift(window).over("industry_code") - 1.0)
                * 100.0
            ).alias(f"return_{window}d")
            for window in RETURN_WINDOWS
        ]
    )
    joined = joined.with_columns(
        (pl.col("amount") / YUAN_PER_YI).alias("amount_yi"),
    )

    result = add_rolling_percentiles(
        joined,
        key="industry_code",
        date_column="trade_date",
        value_columns=list(PERCENTILE_VALUE_COLUMNS),
        window_5y=WINDOW_5Y_DAYS,
        window_10y=WINDOW_10Y_DAYS,
        cutoff_date=percentile_cutoff,
    )

    return result.select(list(INDUSTRY_L2_SCHEMA)).sort(["trade_date", "industry_code"])


__all__ = ["INDUSTRY_L2_MART_NAME", "build_industry_l2_frame", "empty_industry_l2"]
