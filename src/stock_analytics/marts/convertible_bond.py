"""可转债日频领域 Mart。"""

from __future__ import annotations

import polars as pl

from stock_data.pipeline.cleaner.date_utils import parse_mixed_date

CB_MART_NAME = "convertible_bond_daily"


def _empty_mart() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "trade_date": pl.Date,
            "cb_price_median": pl.Float64,
            "cb_conversion_premium_median": pl.Float64,
            "cb_bond_premium_median": pl.Float64,
            "cb_valid_count": pl.Int64,
            "cb_low_price_count": pl.Int64,
            "cb_below_par_count": pl.Int64,
        }
    )


def _median(column: str, frame: pl.DataFrame, alias: str) -> pl.Expr:
    if column not in frame.columns:
        return pl.lit(None, dtype=pl.Float64).alias(alias)
    return pl.col(column).cast(pl.Float64, strict=False).median().alias(alias)


def build_convertible_bond_mart(
    daily: pl.DataFrame,
    *,
    low_price_threshold: float = 110.0,
    par_value: float = 100.0,
) -> pl.DataFrame:
    """从 ``cb_daily`` 构建全市场可转债日频截面聚合。"""
    required = {"trade_date", "close"}
    if daily.is_empty() or not required.issubset(daily.columns):
        return _empty_mart()

    frame = daily.with_columns(
        parse_mixed_date("trade_date").alias("trade_date"),
        pl.col("close").cast(pl.Float64, strict=False).alias("_close"),
    ).drop_nulls(subset=["trade_date", "_close"])
    if frame.is_empty():
        return _empty_mart()

    result = frame.group_by("trade_date").agg(
        pl.col("_close").count().cast(pl.Int64).alias("cb_valid_count"),
        pl.col("_close").median().alias("cb_price_median"),
        _median("cb_over_rate", frame, "cb_conversion_premium_median"),
        _median("bond_over_rate", frame, "cb_bond_premium_median"),
        (pl.col("_close") < low_price_threshold).sum().cast(pl.Int64).alias("cb_low_price_count"),
        (pl.col("_close") <= par_value).sum().cast(pl.Int64).alias("cb_below_par_count"),
    )
    return result.sort("trade_date")


__all__ = ["CB_MART_NAME", "build_convertible_bond_mart"]
