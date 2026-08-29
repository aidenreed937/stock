"""申万一级行业产业资本增减持与回购日频领域 Mart。

将重要股东及董监高增减持（stk_holdertrade）与上市公司股票回购（repurchase）
按申万一级行业聚合，输出各行业增持金额、减持金额、回购金额、净流入金额及
滚动 60 交易日（季度窗口）产业资本净流入指标，供聪明资金流与中观行业配置消费。
"""

from __future__ import annotations

from typing import Any

import polars as pl

INSIDER_INDUSTRY_MART_NAME = "insider_industry_daily"

INSIDER_INDUSTRY_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "industry_code": pl.Utf8,
    "industry_name": pl.Utf8,
    "increase_amount": pl.Float64,
    "decrease_amount": pl.Float64,
    "repurchase_amount": pl.Float64,
    "insider_net_amount": pl.Float64,
    "insider_net_amount_yi_60d": pl.Float64,
    "increase_count": pl.Int64,
    "decrease_count": pl.Int64,
    "repurchase_count": pl.Int64,
}


def empty_insider_industry() -> pl.DataFrame:
    """返回稳定 schema 的空产业资本行业日频 Mart。"""
    return pl.DataFrame(schema=INSIDER_INDUSTRY_SCHEMA)


def build_insider_industry_frame(
    holdertrade: pl.DataFrame,
    repurchase: pl.DataFrame,
    sw_constituents: pl.DataFrame,
    industry_daily: pl.DataFrame,
) -> pl.DataFrame:
    """从增减持、股票回购与申万一级成分构建行业产业资本流向聚合。

    - ``holdertrade`` 需含 ``symbol``、``ann_date``、``in_de``、``change_vol``、``avg_price``；
    - ``repurchase`` 需含 ``symbol``、``ann_date``、``amount``；
    - ``sw_constituents``（``index_member``）需含 ``con_code``、``index_code``、``in_date``、``out_date``；
    - ``industry_daily`` 为申万一级行黄金表，需含 ``trade_date``、``industry_code``、``industry_name``。
    """
    required_ht = {"symbol", "ann_date", "in_de", "change_vol"}
    required_rep = {"symbol", "ann_date", "amount"}
    required_const = {"con_code", "index_code", "in_date", "out_date"}
    required_ind = {"trade_date", "industry_code", "industry_name"}

    if (
        sw_constituents.is_empty()
        or not required_const.issubset(sw_constituents.columns)
        or industry_daily.is_empty()
        or not required_ind.issubset(industry_daily.columns)
    ):
        return empty_insider_industry()

    l1_codes = (
        industry_daily.select(
            pl.col("industry_code").cast(pl.Utf8, strict=False),
            pl.col("industry_name").cast(pl.Utf8, strict=False),
        )
        .drop_nulls(subset=["industry_code", "industry_name"])
        .unique(subset=["industry_code"], keep="last")
    )
    l1_list = l1_codes["industry_code"].to_list()

    constituents = (
        sw_constituents.select(
            "con_code",
            "index_code",
            pl.col("in_date").cast(pl.Date, strict=False),
            pl.col("out_date").cast(pl.Date, strict=False),
        )
        .filter(pl.col("index_code").is_in(l1_list))
        .drop_nulls(subset=["in_date"])
    )

    # 1. 增减持明细映射至行业日频
    if not holdertrade.is_empty() and required_ht.issubset(holdertrade.columns):
        ht_cols = [
            "symbol",
            pl.col("ann_date").cast(pl.Date, strict=False),
            pl.col("in_de").cast(pl.Utf8, strict=False).str.to_uppercase(),
            pl.col("change_vol")
            .abs()
            .cast(pl.Float64, strict=False)
            .fill_null(0.0)
            .alias("change_vol"),
        ]
        if "avg_price" in holdertrade.columns:
            ht_cols.append(pl.col("avg_price").cast(pl.Float64, strict=False).alias("avg_price"))
        else:
            ht_cols.append(pl.lit(None, dtype=pl.Float64).alias("avg_price"))

        ht_prep = (
            holdertrade.select(ht_cols)
            .with_columns(
                (pl.col("change_vol") * pl.col("avg_price")).fill_null(0.0).alias("amount")
            )
            .join(constituents, left_on="symbol", right_on="con_code", how="inner")
            .filter(
                (pl.col("in_date") <= pl.col("ann_date"))
                & (pl.col("out_date").is_null() | (pl.col("out_date") >= pl.col("ann_date")))
            )
        )
        is_buy = pl.col("in_de").is_in(["IN", "BUY", "增持"])
        is_sell = pl.col("in_de").is_in(["DE", "SELL", "减持", "OUT"])

        ht_daily = (
            ht_prep.group_by(["ann_date", "index_code"])
            .agg(
                pl.when(is_buy)
                .then(pl.col("amount"))
                .otherwise(0.0)
                .sum()
                .alias("increase_amount"),
                pl.when(is_sell)
                .then(pl.col("amount"))
                .otherwise(0.0)
                .sum()
                .alias("decrease_amount"),
                is_buy.sum().cast(pl.Int64).alias("increase_count"),
                is_sell.sum().cast(pl.Int64).alias("decrease_count"),
            )
            .rename({"ann_date": "trade_date", "index_code": "industry_code"})
        )
    else:
        ht_daily = pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "industry_code": pl.Utf8,
                "increase_amount": pl.Float64,
                "decrease_amount": pl.Float64,
                "increase_count": pl.Int64,
                "decrease_count": pl.Int64,
            }
        )

    # 2. 回购明细映射至行业日频
    if not repurchase.is_empty() and required_rep.issubset(repurchase.columns):
        rep_prep = (
            repurchase.select(
                [
                    "symbol",
                    pl.col("ann_date").cast(pl.Date, strict=False),
                    pl.col("amount").cast(pl.Float64, strict=False).fill_null(0.0).alias("amount"),
                ]
            )
            .join(constituents, left_on="symbol", right_on="con_code", how="inner")
            .filter(
                (pl.col("in_date") <= pl.col("ann_date"))
                & (pl.col("out_date").is_null() | (pl.col("out_date") >= pl.col("ann_date")))
            )
        )
        rep_daily = (
            rep_prep.group_by(["ann_date", "index_code"])
            .agg(
                pl.col("amount").sum().alias("repurchase_amount"),
                pl.len().cast(pl.Int64).alias("repurchase_count"),
            )
            .rename({"ann_date": "trade_date", "index_code": "industry_code"})
        )
    else:
        rep_daily = pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "industry_code": pl.Utf8,
                "repurchase_amount": pl.Float64,
                "repurchase_count": pl.Int64,
            }
        )

    # 3. 与全市场 31 行业日历底座对齐并计算滚动 60 日指标
    backbone = (
        industry_daily.select(
            [
                pl.col("trade_date").cast(pl.Date, strict=False),
                pl.col("industry_code").cast(pl.Utf8, strict=False),
                pl.col("industry_name").cast(pl.Utf8, strict=False),
            ]
        )
        .drop_nulls(subset=["trade_date", "industry_code"])
        .unique(subset=["trade_date", "industry_code"], keep="last")
        .sort(["industry_code", "trade_date"])
    )

    merged = (
        backbone.join(ht_daily, on=["trade_date", "industry_code"], how="left")
        .join(rep_daily, on=["trade_date", "industry_code"], how="left")
        .with_columns(
            [
                pl.col("increase_amount").fill_null(0.0),
                pl.col("decrease_amount").fill_null(0.0),
                pl.col("increase_count").fill_null(0),
                pl.col("decrease_count").fill_null(0),
                pl.col("repurchase_amount").fill_null(0.0),
                pl.col("repurchase_count").fill_null(0),
            ]
        )
        .with_columns(
            (
                pl.col("increase_amount") + pl.col("repurchase_amount") - pl.col("decrease_amount")
            ).alias("insider_net_amount")
        )
        .sort(["industry_code", "trade_date"])
        .with_columns(
            (
                pl.col("insider_net_amount")
                .rolling_sum(window_size=60, min_samples=1)
                .over("industry_code")
                / 1e8
            ).alias("insider_net_amount_yi_60d")
        )
    )

    return merged.select(list(INSIDER_INDUSTRY_SCHEMA))
