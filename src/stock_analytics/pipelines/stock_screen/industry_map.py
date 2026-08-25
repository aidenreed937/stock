"""申万行业映射构建纯函数。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from stock_analytics.pipelines.stock_screen.sources import StockScreenSources


def build_industry_map(
    sources: StockScreenSources,
    as_of_date: date,
) -> pl.DataFrame:
    """按基准日构建 申万 L1/L2 行业归属表。

    以 index_member 的活跃成员（in_date<=as_of<out_date）为基准，
    通过 index_classify 关联行业名，返回 symbol/l1_name/l2_name。
    """
    members = sources.get("index_member")
    classify = sources.get("index_classify")
    if members.is_empty() or classify.is_empty():
        return pl.DataFrame()
    required = {"index_code", "con_code", "in_date", "out_date"}
    if not required.issubset(set(members.columns)):
        return pl.DataFrame()
    if "index_code" not in classify.columns or "industry_name" not in classify.columns:
        return pl.DataFrame()

    l1 = (
        classify.filter(pl.col("level") == "L1")
        .pipe(_prefer_sw2021)
        .select("index_code", pl.col("industry_name").alias("l1_name"))
    )
    l2 = (
        classify.filter(pl.col("level") == "L2")
        .pipe(_prefer_sw2021)
        .select("index_code", pl.col("industry_name").alias("l2_name"))
    )
    active = members.filter(
        (pl.col("in_date") <= pl.lit(as_of_date))
        & (pl.col("out_date").is_null() | (pl.col("out_date") > pl.lit(as_of_date)))
    ).select("con_code", "index_code")

    result = (
        active.join(l2, on="index_code", how="inner")
        .select("con_code", "l2_name")
        .rename({"con_code": "symbol"})
        .unique(subset=["symbol"], keep="first")
    )
    l1_map = (
        active.join(l1, on="index_code", how="inner")
        .select("con_code", "l1_name")
        .rename({"con_code": "symbol"})
        .filter(pl.col("l1_name").is_not_null())
        .unique(subset=["symbol"], keep="first")
    )
    result = result.join(l1_map, on="symbol", how="left")
    return result.with_columns(pl.col("symbol").cast(pl.String))


def _prefer_sw2021(frame: pl.DataFrame) -> pl.DataFrame:
    """同一 index_code 存在 SW2014/SW2021 两套记录时优先保留 SW2021。"""
    if "src" not in frame.columns:
        return frame.unique(subset=["index_code"], keep="first")
    return (
        frame.with_columns(
            pl.when(pl.col("src") == "SW2021").then(0).otherwise(1).alias("_src_rank")
        )
        .sort("_src_rank")
        .unique(subset=["index_code"], keep="first")
        .drop("_src_rank")
    )


__all__ = ["build_industry_map"]
