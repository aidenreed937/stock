"""嵌套字段、稳定实体与历史数据集后处理兼容规则。"""

from __future__ import annotations

import json
from collections.abc import Sequence

import polars as pl

from stock_data.storage.legacy_compat import normalize_legacy_index_valuation

_LEGACY_INTEREST_RATE_COLUMNS = frozenset({"lpr_y1", "lpr_y5"})
_STABLE_SYMBOL_DATASETS = frozenset(
    {
        "cn_gdp",
        "cn_cpi",
        "cn_ppi",
        "cn_pmi",
        "cn_m",
        "sf_month",
        "shibor",
        "shibor_lpr",
        "stk_account",
    }
)


def _contains_empty_struct(dtype: object) -> bool:
    """递归判断嵌套类型中是否存在 Parquet 不支持的空 struct。"""
    if isinstance(dtype, pl.Struct):
        return not dtype.fields or any(
            _contains_empty_struct(field.dtype) for field in dtype.fields
        )
    inner = getattr(dtype, "inner", None)
    return inner is not None and _contains_empty_struct(inner)


def _json_encode_nested_value(value: object) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(value)


class FrameCompatMixin:
    """处理嵌套字段、稳定标识和历史数据集后处理。"""

    @classmethod
    def normalize_nested_columns(
        cls,
        df: pl.DataFrame,
        reference_frames: Sequence[pl.DataFrame] = (),
    ) -> pl.DataFrame:
        """对齐空嵌套字段，避免 RAW/Curated 写入不可序列化的空 struct。"""
        if df.is_empty():
            return df
        expressions = []
        for column, dtype in df.schema.items():
            if not _contains_empty_struct(dtype):
                continue
            reference_dtype = next(
                (
                    frame.schema[column]
                    for frame in reference_frames
                    if column in frame.columns
                    and isinstance(frame.schema[column], pl.Struct)
                    and not _contains_empty_struct(frame.schema[column])
                ),
                None,
            )
            if isinstance(dtype, pl.Struct) and isinstance(reference_dtype, pl.Struct):
                expressions.append(pl.col(column).cast(reference_dtype, strict=False).alias(column))
            elif isinstance(dtype, pl.Struct):
                expressions.append(pl.col(column).struct.json_encode().alias(column))
            else:
                expressions.append(
                    pl.col(column)
                    .map_elements(_json_encode_nested_value, return_dtype=pl.Utf8)
                    .alias(column)
                )
        return df.with_columns(expressions) if expressions else df

    @staticmethod
    def ensure_dataset_identity(dataset_name: str, df: pl.DataFrame) -> pl.DataFrame:
        """为只有期间主键的宏观序列补齐稳定实体标识。"""
        if df.is_empty() or dataset_name not in _STABLE_SYMBOL_DATASETS:
            return df
        if "symbol" not in df.columns:
            return df.with_columns(pl.lit(dataset_name).alias("symbol"))
        return df.with_columns(
            pl.col("symbol").cast(pl.Utf8, strict=False).fill_null(dataset_name).alias("symbol")
        )

    @staticmethod
    def safe_normalize_frame(df: pl.DataFrame) -> pl.DataFrame:
        """对加载的单个 Parquet 分区执行在线容错预规范化。"""
        if df.is_empty():
            return df
        from stock_data.storage.compat_columns import ColumnCompatMixin

        normalized = ColumnCompatMixin.normalize_identity_columns(df)
        normalized = ColumnCompatMixin.normalize_date_columns(normalized)
        normalized = ColumnCompatMixin.normalize_datetime_columns(normalized)
        return ColumnCompatMixin.normalize_numeric_columns(normalized)

    @staticmethod
    def normalize_dataset_contract_columns(dataset_name: str, df: pl.DataFrame) -> pl.DataFrame:
        """将历史字段映射到数据集规范字段，并固定关键数值类型。"""
        if df.is_empty():
            return df
        normalized = df
        if dataset_name == "express" and "yoy_net_profit" in normalized.columns:
            if "prior_period_net_profit" not in normalized.columns:
                normalized = normalized.rename({"yoy_net_profit": "prior_period_net_profit"})
            else:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col("prior_period_net_profit").cast(pl.Float64, strict=False),
                            pl.col("yoy_net_profit").cast(pl.Float64, strict=False),
                        ]
                    ).alias("prior_period_net_profit")
                ).drop("yoy_net_profit")
        if dataset_name == "national_debt" and "tcm_y10" in normalized.columns:
            normalized = normalized.with_columns(
                pl.col("tcm_y10").cast(pl.Float64, strict=False).alias("tcm_y10")
            )
        return normalized

    @staticmethod
    def post_process_dataset(dataset_name: str, df: pl.DataFrame) -> pl.DataFrame:
        from stock_data.storage.compat_columns import ColumnCompatMixin

        df = ColumnCompatMixin.normalize_financial_statement_columns(dataset_name, df)
        df = ColumnCompatMixin.normalize_date_columns(df)
        df = ColumnCompatMixin.normalize_numeric_columns(df, dataset_name)
        df = FrameCompatMixin.ensure_dataset_identity(dataset_name, df)
        df = normalize_legacy_index_valuation(df) if dataset_name == "index_valuation" else df
        if dataset_name == "hk_hold" and "symbol" in df.columns:
            qualified = df.filter(pl.col("symbol").cast(pl.Utf8, strict=False).str.contains(r"\."))
            if not qualified.is_empty():
                return qualified
        if dataset_name == "margin" and "symbol" in df.columns:
            return df.drop("symbol")
        if dataset_name == "moneyflow_hsgt":
            normalized = df.drop("symbol") if "symbol" in df.columns else df
            return normalized.with_columns(
                pl.lit("CN").alias("market"),
                pl.lit("CNY").alias("currency"),
                pl.lit("SOURCE").alias("exchange"),
            )
        if dataset_name == "sw_daily":
            legacy_cols = [
                "fetched_at",
                "field_provenance",
                "index_id",
                "index_name",
                "industry_id",
                "industry_name",
                "pct_chg",
                "scope_note",
                "source_id",
                "source_index_code",
                "source_scope",
                "source_unit_note",
                "turnover_amount",
            ]
            to_drop = [column for column in legacy_cols if column in df.columns]
            if to_drop:
                return df.drop(to_drop)
        if dataset_name == "interest_rates":
            to_drop = [column for column in _LEGACY_INTEREST_RATE_COLUMNS if column in df.columns]
            if to_drop:
                return df.drop(to_drop)
        return df
