"""北向资金行业持仓日频领域 Mart。

将沪深股通（北向）个股持股明细按申万一级行业聚合，输出各行业北向持仓市值、
家数、占比与环比变化，供外资配置与行业轮动分析直接消费。

口径说明：
- ``hk_hold`` 仅取 A 股行（代码后缀 ``.SH`` / ``.SZ``），``HKEX`` 港股为港股通
  （南向），不在本 Mart；
- ``vol`` 为持股数量（单位"股"，与 ``daily_basic.total_share`` 对账一致）、
  ``ratio`` 为持股市值占该股总市值比例（%）；
- 持仓市值 = 持股数量 × 当日收盘价（``stock_daily_bar`` 未复权价；停牌日顺延
  前一交易日收盘价近似）；
- 个股归属申万一级行业：``index_member`` 成分（``index_code`` 为申万一级指数码，
  按 ``in_date / out_date`` 判定当日有效），行业名取 ``sw_daily`` L1 行；
- 覆盖率如实保留监管披露节奏：2024-08-19 前为日频，其后为季度末快照，
  2016-2023 仅零星采样日；``hold_value_chg`` 与 ``hold_value_pct_chg`` 为相邻
  两个观测日环比（季度快照段即季度环比）。
"""

from __future__ import annotations

from typing import Any

import polars as pl

NORTHBOUND_INDUSTRY_MART_NAME = "northbound_industry_daily"

NORTHBOUND_INDUSTRY_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "industry_code": pl.Utf8,
    "industry_name": pl.Utf8,
    "hold_symbol_count": pl.Int64,
    "hold_share_amount": pl.Float64,
    "hold_value": pl.Float64,
    "hold_value_pct": pl.Float64,
    "hold_value_chg": pl.Float64,
    "hold_value_pct_chg": pl.Float64,
}


def empty_northbound_industry() -> pl.DataFrame:
    """返回稳定 schema 的空北向行业持仓 Mart。"""
    return pl.DataFrame(schema=NORTHBOUND_INDUSTRY_SCHEMA)


def _is_a_share(symbol: pl.Expr) -> pl.Expr:
    """A 股代码标记（沪深股通标的，排除港股通 .HK）。"""
    return pl.col("symbol").str.ends_with(".SH") | pl.col("symbol").str.ends_with(".SZ")


def build_northbound_industry_frame(
    hk_hold: pl.DataFrame,
    sw_constituents: pl.DataFrame,
    sw_daily_l1: pl.DataFrame,
    daily_close: pl.DataFrame,
) -> pl.DataFrame:
    """从北向持股明细与申万一级成分构建行业持仓聚合。

    ``hk_hold`` 需含 ``trade_date``、``symbol``、``vol``、``ratio``（内部过滤 A 股）；
    ``sw_constituents``（``index_member``）需含 ``con_code``、``index_code``、
    ``in_date``、``out_date``；``sw_daily_l1`` 为申万一级行，需含 ``symbol``
    （一级指数码）、``industry_code``、``name``；``daily_close`` 需含 ``symbol``、
    ``trade_date``、``close``。
    """
    schema = NORTHBOUND_INDUSTRY_SCHEMA
    required_hk = {"trade_date", "symbol", "vol", "ratio"}
    required_const = {"con_code", "index_code", "in_date", "out_date"}
    required_l1 = {"symbol", "industry_code", "name"}
    required_close = {"symbol", "trade_date", "close"}
    if (
        hk_hold.is_empty()
        or not required_hk.issubset(hk_hold.columns)
        or sw_constituents.is_empty()
        or not required_const.issubset(sw_constituents.columns)
        or sw_daily_l1.is_empty()
        or not required_l1.issubset(sw_daily_l1.columns)
        or daily_close.is_empty()
        or not required_close.issubset(daily_close.columns)
    ):
        return empty_northbound_industry()

    l1_codes = (
        sw_daily_l1.select(
            "symbol",
            pl.col("industry_code").cast(pl.Utf8, strict=False),
            pl.col("name").cast(pl.Utf8, strict=False),
        )
        .drop_nulls(subset=["industry_code", "name"])
        .unique(subset=["symbol"], keep="last")
        .rename({"symbol": "index_code"})
    )
    constituent_source = sw_constituents
    if "src" in constituent_source.columns:
        constituent_source = constituent_source.filter(pl.col("src") == "SW2021")
    constituents = (
        constituent_source.select(
            "con_code",
            "index_code",
            pl.col("in_date").cast(pl.Date, strict=False),
            pl.col("out_date").cast(pl.Date, strict=False),
        )
        .filter(pl.col("index_code").is_in(l1_codes["index_code"].to_list()))
        .drop_nulls(subset=["in_date"])
        .sort(["con_code", "in_date"])
    )
    a_share = (
        hk_hold.filter(_is_a_share(pl.col("symbol")))
        .select(
            "trade_date",
            "symbol",
            pl.col("vol").cast(pl.Float64, strict=False),
            pl.col("ratio").cast(pl.Float64, strict=False),
        )
        .unique(subset=["trade_date", "symbol"], keep="last")
        .sort(["symbol", "trade_date"])
    )
    closes = (
        daily_close.select(
            "symbol",
            pl.col("trade_date").cast(pl.Date, strict=False),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .drop_nulls(subset=["close"])
        .unique(subset=["symbol", "trade_date"], keep="last")
        .sort(["symbol", "trade_date"])
    )
    priced = a_share.join_asof(
        closes,
        left_on="trade_date",
        right_on="trade_date",
        by="symbol",
        strategy="backward",
        check_sortedness=False,
    ).with_columns((pl.col("vol") * pl.col("close")).alias("_hold_value"))

    # 个股 -> 申万一级：按成分进出日期判定当日有效归属，并补齐行业码与名称
    mapped = (
        priced.join(constituents, left_on="symbol", right_on="con_code", how="left")
        .filter(
            pl.col("index_code").is_not_null()
            & (pl.col("in_date") <= pl.col("trade_date"))
            & (pl.col("out_date").is_null() | (pl.col("out_date") >= pl.col("trade_date")))
        )
        .unique(subset=["trade_date", "symbol"], keep="first")
        .join(l1_codes, on="index_code", how="left")
    )
    if mapped.is_empty():
        return empty_northbound_industry()

    total = mapped.group_by("trade_date").agg(pl.col("_hold_value").sum().alias("_total_value"))
    industry = (
        mapped.group_by("trade_date", "industry_code")
        .agg(
            pl.col("name").first().alias("industry_name"),
            pl.col("symbol").n_unique().cast(pl.Int64).alias("hold_symbol_count"),
            pl.col("vol").sum().alias("hold_share_amount"),
            pl.col("_hold_value").sum().alias("hold_value"),
        )
        .join(total, on="trade_date", how="left")
        .with_columns(
            pl.when(pl.col("_total_value") > 0)
            .then(pl.col("hold_value") / pl.col("_total_value") * 100.0)
            .otherwise(None)
            .alias("hold_value_pct"),
        )
        .sort(["industry_code", "trade_date"])
        .with_columns(
            pl.col("hold_value").diff().over("industry_code").alias("hold_value_chg"),
            (pl.col("hold_value") / pl.col("hold_value").shift(1).over("industry_code") - 1.0)
            .mul(100.0)
            .alias("hold_value_pct_chg"),
        )
        .drop("_total_value")
    )
    return industry.select(list(schema)).sort(["trade_date", "industry_code"])


__all__ = [
    "NORTHBOUND_INDUSTRY_MART_NAME",
    "build_northbound_industry_frame",
    "empty_northbound_industry",
]
