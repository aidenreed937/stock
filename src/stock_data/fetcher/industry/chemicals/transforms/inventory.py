"""期货注册仓单库存 RAW/Curated 转换。"""

import polars as pl

from stock_data.fetcher.industry.chemicals.schemas import (
    FUTURES_INVENTORY_RAW_SCHEMA,
    FUTURES_INVENTORY_SCHEMA,
)


def build_futures_inventory_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    """将采集结果落为源值文本优先的 RAW 表。"""
    if df.is_empty():
        return pl.DataFrame(schema=FUTURES_INVENTORY_RAW_SCHEMA)
    for column in ("raw_content_sha256", "raw_snapshot_path"):
        if column not in df.columns:
            df = df.with_columns(pl.lit("").alias(column))
    return (
        df.with_columns(
            pl.col("inventory").cast(pl.String).alias("inventory_raw"),
            pl.col("change").cast(pl.String).alias("change_raw"),
        )
        .drop(["inventory", "change"])
        .select(list(FUTURES_INVENTORY_RAW_SCHEMA))
    )


def build_futures_inventory_curated_frame(df: pl.DataFrame) -> pl.DataFrame:
    """从 RAW 源值文本恢复标准化仓单事实表。"""
    if df.is_empty():
        return pl.DataFrame(schema=FUTURES_INVENTORY_SCHEMA)
    for column in ("raw_content_sha256", "raw_snapshot_path"):
        if column not in df.columns:
            df = df.with_columns(pl.lit("").alias(column))
    if "inventory_raw" in df.columns:
        df = df.with_columns(
            pl.col("inventory_raw").cast(pl.Float64, strict=False).alias("inventory"),
            pl.col("change_raw").cast(pl.Float64, strict=False).alias("change"),
        ).drop(["inventory_raw", "change_raw"])
    return df.select(list(FUTURES_INVENTORY_SCHEMA)).cast(pl.Schema(FUTURES_INVENTORY_SCHEMA))


__all__ = [
    "build_futures_inventory_curated_frame",
    "build_futures_inventory_raw_frame",
]
