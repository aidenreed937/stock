"""化工月频调研 RAW/Curated 转换。"""

from __future__ import annotations

import polars as pl

from stock_data.fetcher.industry.chemicals.schemas import (
    MONTHLY_SURVEY_RAW_SCHEMA,
    MONTHLY_SURVEY_SCHEMA,
)

_RAW_NUMERIC_COLUMNS = (
    "production_w_tons",
    "operating_rate_pct",
    "factory_inventory_w_tons",
    "inventory_mom_pct",
    "inventory_yoy_pct",
)


def build_monthly_survey_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    """将月频调研数值保存为源值文本，避免 RAW 层承载数值转换。"""
    if df.is_empty():
        return pl.DataFrame(schema=MONTHLY_SURVEY_RAW_SCHEMA)
    for column in ("raw_content_sha256", "raw_snapshot_path"):
        if column not in df.columns:
            df = df.with_columns(pl.lit("").alias(column))
    if "data_status" not in df.columns:
        df = df.with_columns(pl.lit("actual").alias("data_status"))

    work = df
    for column in _RAW_NUMERIC_COLUMNS:
        work = work.with_columns(pl.col(column).cast(pl.String).alias(f"{column}_raw"))
    work = work.drop(list(_RAW_NUMERIC_COLUMNS))
    return work.select(list(MONTHLY_SURVEY_RAW_SCHEMA))


def build_monthly_survey_curated_frame(df: pl.DataFrame) -> pl.DataFrame:
    """从月频调研 RAW 源值恢复标准化 Curated 表。"""
    if df.is_empty():
        return pl.DataFrame(schema=MONTHLY_SURVEY_SCHEMA)

    work = df
    if "production_w_tons_raw" in work.columns:
        casts = {
            column: pl.col(f"{column}_raw").cast(pl.Float64, strict=False)
            for column in _RAW_NUMERIC_COLUMNS
        }
        work = work.with_columns(**casts).drop([f"{column}_raw" for column in _RAW_NUMERIC_COLUMNS])
    if "data_status" not in work.columns:
        work = work.with_columns(pl.lit("actual").alias("data_status"))
    return work.select(list(MONTHLY_SURVEY_SCHEMA)).sort(["product_name", "report_month"])


__all__ = [
    "build_monthly_survey_curated_frame",
    "build_monthly_survey_raw_frame",
]
