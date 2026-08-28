"""限售解禁压力日频领域 Mart。

将 1450 万行 ``share_float`` 限售解禁明细按解禁日聚合为日频事实，量化当日解禁
对市场的潜在供给压力（解禁家数、解禁股数、解禁参考市值与大额解禁家数），供
排雷与解禁冲击分析直接消费。

口径说明：
- ``share_float`` 为 TuShare 限售解禁明细：``float_date`` 为解禁日、``float_share``
  为解禁股份数量（单位"股"，与 ``daily_basic.total_share`` 对账一致）、
  ``float_ratio`` 为解禁股份占总股本比例（%）；
- 解禁市值 = 解禁股数 × 解禁日当日收盘价（``stock_daily_bar`` 未复权价；解禁日
  非交易日时顺延至前一交易日）；个别无当日行情的批次（长期停牌/已退市）不计入
  市值列，但家数与股数统计不受影响；
- 大额解禁定义：单股单日解禁市值 ≥ 10 亿元（``large_threshold`` 可调）；
- 本地仅回填已发生解禁（``float_date`` 不超过最新交易日），不含未来解禁公告。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

UNLOCK_PRESSURE_MART_NAME = "unlock_pressure_daily"

#: 单股单日解禁市值达到该阈值（元）即计为大额解禁
LARGE_UNLOCK_THRESHOLD = 1_000_000_000.0

UNLOCK_PRESSURE_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "unlock_count": pl.Int64,
    "unlock_batch_count": pl.Int64,
    "unlock_share_amount": pl.Float64,
    "unlock_amount": pl.Float64,
    "large_unlock_count": pl.Int64,
    "avg_float_ratio": pl.Float64,
    "max_float_ratio": pl.Float64,
}


def empty_unlock_pressure() -> pl.DataFrame:
    """返回稳定 schema 的空解禁压力 Mart。"""
    return pl.DataFrame(schema=UNLOCK_PRESSURE_SCHEMA)


def build_unlock_pressure_frame(
    share_float: pl.DataFrame,
    daily_close: pl.DataFrame,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    large_threshold: float = LARGE_UNLOCK_THRESHOLD,
) -> pl.DataFrame:
    """从限售解禁明细构建按解禁日的压力聚合。

    ``share_float`` 需含 ``symbol``、``float_date``、``float_share``、``float_ratio``；
    ``daily_close`` 需含 ``symbol``、``trade_date``、``close``（未复权收盘价，元/股）。
    解禁日非交易日时顺延至前一交易日收盘价（as-of 前移）；无行情的批次不计入市值。
    """
    schema = UNLOCK_PRESSURE_SCHEMA
    required_sf = {"symbol", "float_date", "float_share", "float_ratio"}
    required_close = {"symbol", "trade_date", "close"}
    if share_float.is_empty() or not required_sf.issubset(share_float.columns):
        return empty_unlock_pressure()

    sf = share_float.select(
        "symbol",
        "float_date",
        pl.col("float_share").cast(pl.Float64, strict=False),
        pl.col("float_ratio").cast(pl.Float64, strict=False),
    ).sort(["symbol", "float_date"])

    if daily_close.is_empty() or not required_close.issubset(daily_close.columns):
        priced = sf.with_columns(pl.lit(None, dtype=pl.Float64).alias("close"))
    else:
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
        priced = sf.join_asof(
            closes,
            left_on="float_date",
            right_on="trade_date",
            by="symbol",
            strategy="backward",
        )

    priced = priced.with_columns((pl.col("float_share") * pl.col("close")).alias("_amount"))
    base = (
        priced.group_by("float_date")
        .agg(
            pl.col("symbol").n_unique().cast(pl.Int64).alias("unlock_count"),
            pl.len().cast(pl.Int64).alias("unlock_batch_count"),
            pl.col("float_share").fill_null(0.0).sum().alias("unlock_share_amount"),
            # 全组无行情（close 缺失）时金额保持缺失，不假记 0
            pl.when(pl.col("_amount").is_not_null().any())
            .then(pl.col("_amount").sum())
            .otherwise(None)
            .alias("unlock_amount"),
            pl.col("float_ratio").mean().alias("avg_float_ratio"),
            pl.col("float_ratio").max().alias("max_float_ratio"),
        )
        .rename({"float_date": "trade_date"})
    )
    large = (
        priced.group_by("float_date", "symbol")
        .agg(pl.col("_amount").sum().alias("_stock_amount"))
        .filter(pl.col("_stock_amount") >= large_threshold)
        .group_by("float_date")
        .agg(pl.len().cast(pl.Int64).alias("large_unlock_count"))
        .rename({"float_date": "trade_date"})
    )
    result = base.join(large, on="trade_date", how="left").with_columns(
        pl.col("large_unlock_count").fill_null(0).cast(pl.Int64)
    )

    # 若提供了有效的行情交易日历，则按交易日历做对齐并对零解禁日补 0
    if not daily_close.is_empty() and "trade_date" in daily_close.columns:
        calendar = (
            daily_close.select(pl.col("trade_date").cast(pl.Date, strict=False))
            .drop_nulls()
            .unique()
            .sort("trade_date")
        )
        if start_date is not None:
            calendar = calendar.filter(pl.col("trade_date") >= start_date)
        if end_date is not None:
            calendar = calendar.filter(pl.col("trade_date") <= end_date)

        if not calendar.is_empty():
            result = calendar.join(result, on="trade_date", how="full", coalesce=True).with_columns(
                pl.col("unlock_count").fill_null(0).cast(pl.Int64),
                pl.col("unlock_batch_count").fill_null(0).cast(pl.Int64),
                pl.col("unlock_share_amount").fill_null(0.0).cast(pl.Float64),
                pl.col("unlock_amount").fill_null(0.0).cast(pl.Float64),
                pl.col("large_unlock_count").fill_null(0).cast(pl.Int64),
                pl.col("avg_float_ratio").fill_null(0.0).cast(pl.Float64),
                pl.col("max_float_ratio").fill_null(0.0).cast(pl.Float64),
            )

    return result.select(list(schema)).sort("trade_date")


__all__ = ["UNLOCK_PRESSURE_MART_NAME", "build_unlock_pressure_frame", "empty_unlock_pressure"]
