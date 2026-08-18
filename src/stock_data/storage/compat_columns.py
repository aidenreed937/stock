"""跨版本字段名、日期时间与数值类型兼容规则。"""

from __future__ import annotations

import re

import polars as pl

from stock_data.storage.compat_rules import _KNOWN_FLOAT_COLUMNS

_YFINANCE_FINANCIAL_DATASETS = frozenset({"financials", "balance_sheet", "cashflow"})


class ColumnCompatMixin:
    """处理历史字段别名与基础列类型归一。"""

    @staticmethod
    def normalize_identity_columns(df: pl.DataFrame) -> pl.DataFrame:
        """将历史/源端标的与日期别名归一为 Curated 标准列。"""
        normalized = df
        for alias in ("ts_code", "stockCode"):
            if alias not in normalized.columns:
                continue
            if "symbol" not in normalized.columns:
                normalized = normalized.rename({alias: "symbol"})
            else:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col(alias).cast(pl.Utf8, strict=False),
                            pl.col("symbol").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("symbol")
                ).drop(alias)
        if "code" in normalized.columns:
            if "symbol" not in normalized.columns:
                normalized = normalized.rename({"code": "symbol"})
            else:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col("symbol").cast(pl.Utf8, strict=False),
                            pl.col("code").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("symbol")
                ).drop("code")
        if "date" in normalized.columns:
            if "trade_date" not in normalized.columns:
                normalized = normalized.rename({"date": "trade_date"})
            else:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col("trade_date").cast(pl.Utf8, strict=False),
                            pl.col("date").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("trade_date")
                ).drop("date")
        if "asOfDate" in normalized.columns:
            if "as_of_date" not in normalized.columns:
                normalized = normalized.rename({"asOfDate": "as_of_date"})
            else:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col("as_of_date").cast(pl.Utf8, strict=False),
                            pl.col("asOfDate").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("as_of_date")
                ).drop("asOfDate")
        return normalized

    @classmethod
    def normalize_financial_statement_columns(
        cls, dataset_name: str, df: pl.DataFrame
    ) -> pl.DataFrame:
        """将 yfinance 财报标题式字段统一为 Curated snake_case 字段。"""
        if df.is_empty() or dataset_name not in _YFINANCE_FINANCIAL_DATASETS:
            return df

        def snake_case(value: str) -> str:
            text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
            text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
            return re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()

        normalized = df
        for column in list(normalized.columns):
            target = "as_of_date" if column in {"asOfDate", "Date", "date"} else snake_case(column)
            if target == column:
                continue
            if target in normalized.columns:
                normalized = normalized.with_columns(
                    pl.coalesce(
                        [
                            pl.col(target),
                            pl.col(column).cast(normalized.schema[target], strict=False),
                        ]
                    ).alias(target)
                ).drop(column)
            else:
                normalized = normalized.rename({column: target})
        return cls.safe_cast_date_col(normalized, "as_of_date")

    @staticmethod
    def safe_cast_date_col(df: pl.DataFrame, col_name: str = "trade_date") -> pl.DataFrame:
        """安全地将指定日期列规范化为 pl.Date 类型。"""
        if col_name not in df.columns or df.is_empty():
            return df
        dtype = df[col_name].dtype
        if dtype == pl.Date:
            return df
        if dtype == pl.Datetime:
            return df.with_columns(pl.col(col_name).dt.date().alias(col_name))
        return df.with_columns(
            pl.coalesce(
                [
                    pl.col(col_name)
                    .cast(pl.Utf8, strict=False)
                    .str.to_date("%Y-%m-%d", strict=False),
                    pl.col(col_name)
                    .cast(pl.Utf8, strict=False)
                    .str.to_date("%Y%m%d", strict=False),
                ]
            ).alias(col_name)
        )

    @staticmethod
    def normalize_datetime_columns(df: pl.DataFrame) -> pl.DataFrame:
        """将合并中的 datetime 列统一为 UTC 微秒精度。"""
        target_dtype = pl.Datetime(time_unit="us", time_zone="UTC")
        expressions = []
        for column, dtype in df.schema.items():
            if not isinstance(dtype, pl.Datetime):
                continue
            expression = pl.col(column)
            expression = (
                expression.dt.replace_time_zone("UTC")
                if dtype.time_zone is None
                else expression.dt.convert_time_zone("UTC")
            )
            expressions.append(expression.cast(target_dtype).alias(column))
        return df.with_columns(expressions) if expressions else df

    @staticmethod
    def normalize_numeric_columns(df: pl.DataFrame) -> pl.DataFrame:
        """将历史残留的 String 数值度量列安全转为 Float64。"""
        casts = [
            pl.col(column).cast(pl.Float64, strict=False).alias(column)
            for column in df.columns
            if column in _KNOWN_FLOAT_COLUMNS and df.schema[column] in (pl.Utf8, pl.String)
        ]
        return df.with_columns(casts) if casts else df
