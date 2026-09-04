"""Avnet/Arrow 渠道库存 Curated 转换器。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import polars as pl

from stock_data.fetcher.industry.semiconductor.schemas import (
    CHANNEL_INVENTORY_CURATED_SCHEMA,
    CHANNEL_INVENTORY_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)


def build_channel_inventory_raw_frame(
    items: Sequence[dict[str, Any]] | pl.DataFrame,
) -> pl.DataFrame:
    """将 SEC companyfacts 解析结果整理为源端字段/字符串值优先的 RAW 帧。"""
    if isinstance(items, pl.DataFrame):
        if items.is_empty() and not items.columns:
            return pl.DataFrame(schema=CHANNEL_INVENTORY_RAW_SCHEMA)
        df = _with_missing_columns(items, CHANNEL_INVENTORY_RAW_SCHEMA)
    elif not items:
        return pl.DataFrame(schema=CHANNEL_INVENTORY_RAW_SCHEMA)
    else:
        df = pl.DataFrame(items)

    return require_raw_release_dates(
        (
            _with_missing_columns(df, CHANNEL_INVENTORY_RAW_SCHEMA)
            .select(list(CHANNEL_INVENTORY_RAW_SCHEMA))
            .with_columns(
                [
                    pl.col(name).cast(dtype, strict=False).alias(name)
                    for name, dtype in CHANNEL_INVENTORY_RAW_SCHEMA.items()
                ]
            )
            .unique(subset=["report_quarter", "symbol"], keep="last")
            .sort(["trade_date", "symbol"])
        ),
        "semiconductor_channel_inventory",
    )


def build_channel_inventory_curated_frame(df_raw: pl.DataFrame) -> pl.DataFrame:
    """从渠道商 RAW 字段计算单公司和渠道整体库存周转天数。"""
    raw = build_channel_inventory_raw_frame(df_raw)
    if raw.is_empty():
        return pl.DataFrame(schema=CHANNEL_INVENTORY_CURATED_SCHEMA)

    base = raw.with_columns(
        (_numeric_expr("inventory_usd_raw") / 1_000_000.0).round(3).alias("inventory_usd_million"),
        (_numeric_expr("cost_of_revenue_usd_raw") / 1_000_000.0)
        .round(3)
        .alias("cost_of_revenue_usd_million"),
    ).with_columns(
        pl.when(pl.col("cost_of_revenue_usd_million") > 0)
        .then(
            (pl.col("inventory_usd_million") / pl.col("cost_of_revenue_usd_million") * 90.0).round(
                1
            )
        )
        .otherwise(None)
        .alias("channel_doi_days")
    )
    aggregate = (
        base.group_by("report_quarter")
        .agg(
            pl.col("inventory_usd_million").sum().alias("channel_total_inventory_usd_million"),
            pl.col("cost_of_revenue_usd_million")
            .sum()
            .alias("channel_total_cost_of_revenue_usd_million"),
            pl.col("channel_doi_days").mean().round(1).alias("channel_equal_doi_days"),
        )
        .with_columns(
            pl.when(pl.col("channel_total_cost_of_revenue_usd_million") > 0)
            .then(
                (
                    pl.col("channel_total_inventory_usd_million")
                    / pl.col("channel_total_cost_of_revenue_usd_million")
                    * 90.0
                ).round(1)
            )
            .otherwise(None)
            .alias("channel_weighted_doi_days")
        )
    )

    return (
        base.join(aggregate, on="report_quarter", how="left")
        .with_columns(pl.lit("million_usd/days").alias("unit"))
        .select(list(CHANNEL_INVENTORY_CURATED_SCHEMA))
        .with_columns(
            [
                pl.col(name).cast(dtype, strict=False).alias(name)
                for name, dtype in CHANNEL_INVENTORY_CURATED_SCHEMA.items()
            ]
        )
        .sort(["trade_date", "symbol"])
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
