"""海关公司面板共享的月频趋势派生函数。"""

from __future__ import annotations

import polars as pl


def _derive(df: pl.DataFrame, key: str, all_months: list[str]) -> pl.DataFrame:
    """按 key 补全月序，重算 3MMA 值/量/价 yoy、驱动与拐点。"""
    base = pl.DataFrame({key: df[key].unique().to_list()}).join(
        pl.DataFrame({"report_month": all_months}), how="cross"
    )
    df = base.join(df, on=[key, "report_month"], how="left")
    return (
        df.sort([key, "report_month"])
        .with_columns(
            pl.col("export_value_usd").rolling_mean(3, min_samples=3).over(key).alias("v3"),
            pl.col("export_volume").rolling_mean(3, min_samples=3).over(key).alias("q3"),
        )
        .with_columns(
            (pl.col("v3") / pl.col("v3").shift(12).over(key) - 1).alias("value_yoy_3mma"),
            (pl.col("q3") / pl.col("q3").shift(12).over(key) - 1).alias("volume_yoy_3mma"),
        )
        .with_columns((pl.col("v3") / pl.col("q3")).alias("asp_3mma"))
        .with_columns(
            (pl.col("asp_3mma") / pl.col("asp_3mma").shift(12).over(key) - 1).alias(
                "price_yoy_3mma"
            )
        )
        .with_columns(
            pl.when(pl.col("volume_yoy_3mma").is_nan() | pl.col("price_yoy_3mma").is_nan())
            .then(None)
            .when((pl.col("volume_yoy_3mma") > 0) & (pl.col("price_yoy_3mma") > 0))
            .then(pl.lit("量价齐升"))
            .when((pl.col("volume_yoy_3mma") > 0) & (pl.col("price_yoy_3mma") <= 0))
            .then(pl.lit("量驱动"))
            .when((pl.col("volume_yoy_3mma") <= 0) & (pl.col("price_yoy_3mma") > 0))
            .then(pl.lit("价驱动"))
            .when((pl.col("volume_yoy_3mma") <= 0) & (pl.col("price_yoy_3mma") <= 0))
            .then(pl.lit("双弱"))
            .otherwise(None)
            .alias("驱动类型")
        )
        .with_columns(
            pl.when(
                (pl.col("value_yoy_3mma").shift(1).over(key) < 0) & (pl.col("value_yoy_3mma") >= 0)
            )
            .then(pl.lit("启动拐点"))
            .when(
                (pl.col("value_yoy_3mma").shift(1).over(key) > 0) & (pl.col("value_yoy_3mma") <= 0)
            )
            .then(pl.lit("见顶拐点"))
            .otherwise(None)
            .alias("拐点"),
            pl.when(
                (pl.col("volume_yoy_3mma") >= 0)
                & (
                    pl.col("volume_yoy_3mma")
                    < pl.col("volume_yoy_3mma").rolling_max(4, min_samples=2).shift(1).over(key)
                )
                & (pl.col("volume_yoy_3mma").rolling_max(6, min_samples=3).over(key) > 0.1)
            )
            .then(pl.lit("量增速回落"))
            .otherwise(None)
            .alias("二阶导"),
        )
    )
