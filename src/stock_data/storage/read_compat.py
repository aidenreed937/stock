"""Curated Parquet 读取兼容层。"""

from pathlib import Path

import polars as pl

from stock_core.exceptions import DataValidationError
from stock_data.storage.compat import StorageCompat
from stock_data.storage.compat_rules import (
    _IDENTITY_ALIASES,
    _KNOWN_DATE_COLUMNS,
    numeric_columns_for_dataset,
)


def requires_read_normalization(path: Path, dataset_name: str) -> bool:
    """判断 Parquet 是否需要先经过统一读取兼容层。"""
    try:
        schema = pl.read_parquet_schema(path)
    except Exception:
        return True
    if _IDENTITY_ALIASES.intersection(schema):
        return True
    if dataset_name in {"hk_hold", "margin", "moneyflow_hsgt", "sw_daily"}:
        return True
    if dataset_name == "interest_rates":
        return any(column in schema for column in ("lpr_y1", "lpr_y5"))
    if dataset_name == "index_valuation" and "total_assets" in schema:
        return True
    if dataset_name == "express" and "yoy_net_profit" in schema:
        return True
    if dataset_name == "national_debt" and "tcm_y10" in schema:
        return schema["tcm_y10"] in (pl.Utf8, pl.String)
    if "trade_date" in schema and schema["trade_date"] != pl.Date:
        return True
    if "as_of_date" in schema and schema["as_of_date"] != pl.Date:
        return True
    if any(
        column in schema and schema[column] != pl.Date
        for column in _KNOWN_DATE_COLUMNS - {"month", "quarter"}
    ):
        return True
    if "updated_at" in schema:
        updated_at_dtype = schema["updated_at"]
        if not isinstance(updated_at_dtype, pl.Datetime) or updated_at_dtype.time_zone != "UTC":
            return True
    known_numeric = numeric_columns_for_dataset(dataset_name, schema)
    return any(
        column in known_numeric and dtype in (pl.Utf8, pl.String, pl.Null)
        for column, dtype in schema.items()
    )


def normalize_read_frame(dataset_name: str, df: pl.DataFrame) -> pl.DataFrame:
    """将单个历史 Parquet 分区归一化为统一读取字段。"""
    if df.is_empty():
        return df
    normalized = StorageCompat.safe_normalize_frame(df)
    normalized = StorageCompat.normalize_dataset_contract_columns(dataset_name, normalized)
    return StorageCompat.post_process_dataset(dataset_name, normalized)


def validate_schema_version(df: pl.DataFrame, context: object) -> None:
    """拒绝读取已标记为旧版或未知版本的 Curated 数据。"""
    if "schema_version" not in df.columns or df.is_empty():
        return
    versions = {
        str(value)
        for value in df.get_column("schema_version")
        .cast(pl.Utf8, strict=False)
        .drop_nulls()
        .unique()
        .to_list()
        if str(value)
    }
    invalid = versions - {"v2"}
    if invalid:
        raise DataValidationError(
            f"文件 [{context}] 包含旧版或未知 schema_version: {sorted(invalid)}"
        )
