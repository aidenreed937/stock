"""TrendForce DRAM/NAND 价格 Curated 转换器。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import polars as pl

from stock_data.fetcher.industry.semiconductor.schemas import (
    MEMORY_PRICE_CURATED_SCHEMA,
    MEMORY_PRICE_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)

_PRICE_RAW_COLUMNS = (
    "daily_high_raw",
    "daily_low_raw",
    "session_high_raw",
    "session_low_raw",
    "session_average_raw",
    "high_raw",
    "low_raw",
    "average_raw",
)

_CHANGE_RAW_COLUMNS = (
    "session_change_raw",
    "average_change_raw",
    "low_change_raw",
)


def build_memory_price_raw_frame(items: Sequence[dict[str, Any]] | pl.DataFrame) -> pl.DataFrame:
    """将 TrendForce HTML 解析结果整理为源端字段/字符串值优先的 RAW 帧。"""
    if isinstance(items, pl.DataFrame):
        if items.is_empty() and not items.columns:
            return pl.DataFrame(schema=MEMORY_PRICE_RAW_SCHEMA)
        df = _with_missing_columns(items, MEMORY_PRICE_RAW_SCHEMA)
    elif not items:
        return pl.DataFrame(schema=MEMORY_PRICE_RAW_SCHEMA)
    else:
        df = pl.DataFrame(items)

    return require_raw_release_dates(
        (
            _with_missing_columns(df, MEMORY_PRICE_RAW_SCHEMA)
            .select(list(MEMORY_PRICE_RAW_SCHEMA))
            .with_columns(
                [
                    pl.col(name).cast(dtype, strict=False).alias(name)
                    for name, dtype in MEMORY_PRICE_RAW_SCHEMA.items()
                ]
            )
            .unique(
                subset=["trade_date", "product_family", "price_scope", "table_index", "item_raw"],
                keep="last",
            )
            .sort(["trade_date", "product_family", "price_scope", "table_index", "item_raw"])
        ),
        "semiconductor_memory_price",
    )


def build_memory_price_curated_frame(df_raw: pl.DataFrame) -> pl.DataFrame:
    """从 TrendForce RAW 字符串字段生成标准化 DRAM/NAND 价格事实。"""
    raw = build_memory_price_raw_frame(df_raw)
    if raw.is_empty():
        return pl.DataFrame(schema=MEMORY_PRICE_CURATED_SCHEMA)

    price_exprs = [
        _numeric_expr(raw_column).alias(raw_column.removesuffix("_raw") + "_usd")
        for raw_column in _PRICE_RAW_COLUMNS
    ]
    change_exprs = [
        _percent_expr(raw_column).alias(raw_column.removesuffix("_raw"))
        for raw_column in _CHANGE_RAW_COLUMNS
    ]
    return (
        raw.with_columns(
            pl.col("updated_at_raw").alias("updated_at"),
            pl.col("item_raw").str.strip_chars().alias("item"),
            *price_exprs,
            *change_exprs,
            pl.lit("usd_per_unit").alias("unit"),
        )
        .select(list(MEMORY_PRICE_CURATED_SCHEMA))
        .with_columns(
            [
                pl.col(name).cast(dtype, strict=False).alias(name)
                for name, dtype in MEMORY_PRICE_CURATED_SCHEMA.items()
            ]
        )
        .sort(["trade_date", "product_family", "price_scope", "table_index", "item"])
    )


def _with_missing_columns(df: pl.DataFrame, schema: dict[str, Any]) -> pl.DataFrame:
    additions: list[pl.Expr] = []
    for column, dtype in schema.items():
        if column not in df.columns:
            additions.append(pl.lit(None, dtype=dtype).alias(column))
    return df.with_columns(additions) if additions else df


def _numeric_expr(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.String)
        .str.replace_all(r"[^\d.-]", "")
        .cast(pl.Float64, strict=False)
    )


def _percent_expr(column: str) -> pl.Expr:
    raw = pl.col(column).cast(pl.String)
    value = _numeric_expr(column)
    return (
        pl.when(raw.str.contains(r"%|percent", literal=False))
        .then(value / 100.0)
        .otherwise(value)
        .round(6)
    )
