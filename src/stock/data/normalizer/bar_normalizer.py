"""日 K 线行情数据标准化器实现。"""

import polars as pl

from stock.data.normalizer.base import BaseDataNormalizer
from stock.utils.logger import logger

# 常见外部数据源别名映射表 (例如 TuShare / AKShare -> 内部统一规范列名)
COLUMN_MAPPING = {
    "ts_code": "symbol",
    "code": "symbol",
    "vol": "volume",
    "date": "trade_date",
    "datetime": "trade_date",
}

# 内部统一 Exact Schema 标准列顺序 (16 列固定顺序)
STANDARD_COLUMNS = [
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "data_source",
    "source_endpoint",
    "market",
    "exchange",
    "currency",
    "adjustment",
    "schema_version",
    "updated_at",
]


class BarDataNormalizer(BaseDataNormalizer):
    """日 K 线数据标准化器，负责列名别名对齐、日期格式统一与标准列排序。"""

    def normalize(self, df: pl.DataFrame) -> pl.DataFrame:
        """标准化日 K 线行情数据帧。

        Args:
            df: 经过 Cleaner 与 UnitNormalizer 处理的数据帧。

        Returns:
            pl.DataFrame: 标准化对齐后的 Polars DataFrame。
        """
        if df.is_empty():
            logger.warning("传入待标准化的数据帧为空，跳过标准化")
            return df

        normalized_df = df

        # 1. 统一列名映射
        rename_dict = {
            old_col: new_col
            for old_col, new_col in COLUMN_MAPPING.items()
            if old_col in normalized_df.columns and new_col not in normalized_df.columns
        }
        if rename_dict:
            normalized_df = normalized_df.rename(rename_dict)

        # 2. 转换 trade_date 为 Date 类型
        if "trade_date" in normalized_df.columns:
            dtype = normalized_df["trade_date"].dtype
            if dtype == pl.String or dtype == pl.Utf8:
                non_null_vals = normalized_df["trade_date"].drop_nulls()
                if not non_null_vals.is_empty():
                    first_val = str(non_null_vals[0])
                    if "T" in first_val:
                        normalized_df = normalized_df.with_columns(
                            pl.col("trade_date").str.slice(0, 10).str.to_date("%Y-%m-%d").alias("trade_date")
                        )
                    else:
                        fmt = "%Y%m%d" if len(first_val) == 8 else "%Y-%m-%d"
                        normalized_df = normalized_df.with_columns(
                            pl.col("trade_date").str.to_date(fmt, strict=False).alias("trade_date")
                        )

        # 3. 强制数值列类型转换
        num_exprs = []
        for num_col in ("open", "high", "low", "close", "volume", "amount"):
            if num_col in normalized_df.columns:
                num_exprs.append(pl.col(num_col).cast(pl.Float64, strict=False).alias(num_col))
        if num_exprs:
            normalized_df = normalized_df.with_columns(num_exprs)

        # 4. 移除历史明细记录统计字段 (若存在)
        for legacy_col in ("raw_row_count", "clean_row_count"):
            if legacy_col in normalized_df.columns:
                normalized_df = normalized_df.drop(legacy_col)

        # 5. 按统一的标准列名过滤并排序
        existing_std_cols = [c for c in STANDARD_COLUMNS if c in normalized_df.columns]
        other_cols = [c for c in normalized_df.columns if c not in STANDARD_COLUMNS and c not in ("raw_row_count", "clean_row_count")]

        normalized_df = normalized_df.select(existing_std_cols + other_cols)
        logger.debug(f"数据标准化完成，包含列: {normalized_df.columns}")

        return normalized_df


def infer_market_exchange_currency(
    col_ref: pl.Expr, data_source: str = "tushare"
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """根据证券代码前缀/后缀及数据源动态推算市场 (market)、交易所 (exchange) 与交易货币 (currency)。"""
    default_m = "CN" if data_source.lower() in ("tushare", "lixinger") else "US"
    default_cur = "CNY" if data_source.lower() in ("tushare", "lixinger") else "USD"

    market_expr = (
        pl.when(
            col_ref.str.to_uppercase().str.ends_with(".SH")
            | col_ref.str.to_uppercase().str.ends_with(".SS")
            | col_ref.str.to_uppercase().str.ends_with(".SZ")
            | col_ref.str.to_uppercase().str.ends_with(".BJ")
        )
        .then(pl.lit("CN"))
        .when(col_ref.str.to_uppercase().str.ends_with(".HK"))
        .then(pl.lit("HK"))
        .otherwise(pl.lit(default_m))
    )
    exchange_expr = (
        pl.when(
            col_ref.str.to_uppercase().str.ends_with(".SH")
            | col_ref.str.to_uppercase().str.ends_with(".SS")
        )
        .then(pl.lit("SSE"))
        .when(col_ref.str.to_uppercase().str.ends_with(".SZ"))
        .then(pl.lit("SZSE"))
        .when(col_ref.str.to_uppercase().str.ends_with(".BJ"))
        .then(pl.lit("BSE"))
        .when(col_ref.str.to_uppercase().str.ends_with(".HK"))
        .then(pl.lit("HKEX"))
        .otherwise(pl.lit("US_EXCHANGE"))
    )
    currency_expr = (
        pl.when(
            col_ref.str.to_uppercase().str.ends_with(".SH")
            | col_ref.str.to_uppercase().str.ends_with(".SS")
            | col_ref.str.to_uppercase().str.ends_with(".SZ")
            | col_ref.str.to_uppercase().str.ends_with(".BJ")
        )
        .then(pl.lit("CNY"))
        .when(col_ref.str.to_uppercase().str.ends_with(".HK"))
        .then(pl.lit("HKD"))
        .otherwise(pl.lit("USD"))
    )
    return market_expr, exchange_expr, currency_expr
