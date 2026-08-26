"""市场成交额集中度派生指标。"""

from __future__ import annotations

import polars as pl


def amount_top_5pct_daily_frame(stock_daily_bar: pl.DataFrame) -> pl.DataFrame:
    """按交易日计算有效股票成交额 Top5% 的聚合中间结果。"""
    if stock_daily_bar.is_empty() or not {"trade_date", "amount"}.issubset(stock_daily_bar.columns):
        return pl.DataFrame()
    frame = (
        stock_daily_bar.select(
            pl.col("trade_date").cast(pl.Date, strict=False),
            pl.col("amount").cast(pl.Float64, strict=False).alias("_amount"),
        )
        .drop_nulls()
        .filter(pl.col("_amount") > 0)
    )
    if frame.is_empty():
        return pl.DataFrame()
    ranked = (
        frame.with_columns(
            pl.col("_amount")
            .rank(method="ordinal", descending=True)
            .over("trade_date")
            .alias("_rank"),
            pl.len().over("trade_date").alias("_sample_size"),
        )
        .with_columns(
            pl.max_horizontal(
                (pl.col("_sample_size").cast(pl.Float64) * 0.05).ceil(),
                pl.lit(1.0),
            )
            .cast(pl.Int64)
            .alias("_top_count")
        )
        .with_columns(
            pl.when(pl.col("_rank") <= pl.col("_top_count"))
            .then(pl.col("_amount"))
            .otherwise(0.0)
            .alias("_top_amount")
        )
    )
    return (
        ranked.group_by("trade_date")
        .agg(
            pl.col("_top_amount").sum().alias("_top_amount"),
            pl.col("_amount").sum().alias("_total_amount"),
            pl.col("_sample_size").first().alias("_sample_size"),
            pl.col("_top_count").first().alias("_top_count"),
        )
        .with_columns((pl.col("_top_amount") / pl.col("_total_amount")).alias("_top_share"))
        .sort("trade_date")
    )


__all__ = ["amount_top_5pct_daily_frame"]
