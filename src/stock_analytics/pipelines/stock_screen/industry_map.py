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
    golden = sources.get("sw_2021_industry_member_golden")
    if not golden.is_empty():
        stock_basic = sources.get("stock_basic")
        symbol_map = {}
        if not stock_basic.is_empty() and "symbol" in stock_basic.columns:
            symbol_map = {
                str(symbol).split(".", 1)[0]: str(symbol)
                for symbol in stock_basic.get_column("symbol").to_list()
            }
        return _build_industry_map_from_golden(golden, as_of_date, symbol_map=symbol_map)

    members = sources.get("index_member_versioned")
    if members.is_empty():
        members = sources.get("index_member")
    elif "src" in members.columns:
        members = members.filter(pl.col("src") == "SW2021")
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


def _build_industry_map_from_golden(
    golden: pl.DataFrame,
    as_of_date: date,
    *,
    symbol_map: dict[str, str] | None = None,
) -> pl.DataFrame:
    """从跨源黄金成员表切出基准日 L1/L2 归属。"""
    required = {
        "symbol",
        "industry_code",
        "level",
        "valid_from",
        "valid_to",
        "is_canonical",
    }
    if not required.issubset(golden.columns):
        return pl.DataFrame()
    active = golden.filter(
        pl.col("is_canonical")
        & (pl.col("valid_from").is_null() | (pl.col("valid_from") <= as_of_date))
        & (pl.col("valid_to").is_null() | (pl.col("valid_to") > as_of_date))
    )
    if {"snapshot_date", "src"}.issubset(active.columns):
        active = active.filter(
            (pl.col("src") != "LIXINGER")
            | (pl.col("snapshot_date").is_not_null() & (pl.col("snapshot_date") <= as_of_date))
        )
    if active.is_empty():
        return pl.DataFrame()

    def _level_map(level: str, name: str) -> pl.DataFrame:
        columns = ["symbol", "industry_code"]
        if name in active.columns:
            columns.append(name)
        result = active.filter(pl.col("level") == level).select(columns)
        if name not in result.columns:
            result = result.with_columns(pl.lit(None, dtype=pl.String).alias(name))
        return (
            result.sort(["symbol", "industry_code"])
            .unique(subset=["symbol"], keep="first", maintain_order=True)
            .rename({"symbol": "_symbol"})
        )

    l1 = _level_map("L1", "industry_name").rename({"industry_name": "l1_name"})
    l2 = _level_map("L2", "industry_name").rename({"industry_name": "l2_name"})
    if l1.is_empty() and l2.is_empty():
        return pl.DataFrame()
    if l1.is_empty():
        result = l2.rename({"_symbol": "symbol"}).select("symbol", "l2_name")
    elif l2.is_empty():
        result = l1.rename({"_symbol": "symbol"}).select("symbol", "l1_name")
    else:
        result = (
            l2.join(l1, on="_symbol", how="full", suffix="_l1")
            .with_columns(pl.coalesce([pl.col("_symbol"), pl.col("_symbol_l1")]).alias("symbol"))
            .select("symbol", "l2_name", "l1_name")
        )
    if not symbol_map:
        return result
    return result.with_columns(
        pl.col("symbol")
        .map_elements(lambda value: symbol_map.get(str(value), str(value)), return_dtype=pl.String)
        .alias("symbol")
    )


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
