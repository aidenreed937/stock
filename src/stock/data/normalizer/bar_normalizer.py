"""日 K 线行情数据标准化器实现。"""

import polars as pl

from stock.core.contracts import InstrumentId
from stock.data.normalizer.base import BaseDataNormalizer
from stock.utils.date import parse_mixed_date
from stock.utils.logger import logger

# 常见外部数据源别名映射表 (例如 TuShare / AKShare -> 内部统一规范列名)
COLUMN_MAPPING = {
    "ts_code": "symbol",
    "stockCode": "symbol",
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

# TuShare 个股日线的 Curated 固定列集合。RAW 中的 scope_note/source_scope
# 属于旧批次附加元数据，证据仍保留在 RAW，不进入下游黄金表。
CURATED_STOCK_DAILY_BAR_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "name",
    "pre_close",
    "change",
    "pct_chg",
    "source_unit_note",
    "source_id",
    "fetched_at",
    "data_source",
    "source_endpoint",
    "request_id",
    "updated_at",
    "market",
    "exchange",
    "currency",
    "adjustment",
    "schema_version",
)

_CURATED_BAR_FLOAT_COLUMNS = frozenset(
    {"open", "high", "low", "close", "volume", "amount", "pre_close", "change", "pct_chg"}
)
_CURATED_BAR_STRING_COLUMNS = frozenset(
    set(CURATED_STOCK_DAILY_BAR_COLUMNS)
    - _CURATED_BAR_FLOAT_COLUMNS
    - {"trade_date", "updated_at"}
)


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
            normalized_df = normalized_df.with_columns(
                parse_mixed_date("trade_date").alias("trade_date")
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
        other_cols = [
            c
            for c in normalized_df.columns
            if c not in STANDARD_COLUMNS and c not in ("raw_row_count", "clean_row_count")
        ]

        normalized_df = normalized_df.select(existing_std_cols + other_cols)
        logger.debug(f"数据标准化完成，包含列: {normalized_df.columns}")

        return normalized_df


def _curated_bar_column_expr(df: pl.DataFrame, column: str) -> pl.Expr:
    if column not in df.columns:
        if column in _CURATED_BAR_FLOAT_COLUMNS:
            return pl.lit(None, dtype=pl.Float64).alias(column)
        elif column == "trade_date":
            return pl.lit(None, dtype=pl.Date).alias(column)
        elif column == "updated_at":
            return pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias(column)
        return pl.lit(None, dtype=pl.Utf8).alias(column)
    if column in _CURATED_BAR_FLOAT_COLUMNS:
        return pl.col(column).cast(pl.Float64, strict=False).alias(column)
    if column in _CURATED_BAR_STRING_COLUMNS:
        return pl.col(column).cast(pl.Utf8, strict=False).alias(column)
    if column == "trade_date":
        return parse_mixed_date("trade_date").alias(column)
    return pl.col(column).cast(pl.Datetime("us", "UTC"), strict=False).alias(column)


def normalize_stock_daily_bar_curated_schema(df: pl.DataFrame) -> pl.DataFrame:
    """将 TuShare 个股日线整理为稳定的 Curated Schema。"""
    if df.is_empty():
        return df

    expressions = [
        _curated_bar_column_expr(df, column) for column in CURATED_STOCK_DAILY_BAR_COLUMNS
    ]
    return df.with_columns(expressions).select(list(CURATED_STOCK_DAILY_BAR_COLUMNS))


def infer_market_exchange_currency(
    col_ref: pl.Expr, data_source: str = "tushare"
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """根据证券代码与数据源推算市场、交易所与交易货币。"""
    default_m = "CN" if data_source.lower() in ("tushare", "lixinger") else "US"
    default_ex = "CN" if data_source.lower() in ("tushare", "lixinger") else "US_EXCHANGE"
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
        .otherwise(pl.lit(default_ex))
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
        .otherwise(pl.lit(default_cur))
    )
    return market_expr, exchange_expr, currency_expr


def infer_metadata_expressions(
    normalized_df: pl.DataFrame,
    instrument: InstrumentId | None,
    data_source: str,
    api_name: str,
    dataset: str | None,
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """根据任务、标的和数据源推算血缘市场元数据。"""
    if data_source in {"alphavantage", "yfinance"} and (
        dataset == "macro_indicators"
        or api_name in {"macro_indicators", "FX_DAILY"}
    ):
        return pl.lit("GLOBAL"), pl.lit("GLOBAL"), pl.lit("USD")
    if instrument:
        return pl.lit(instrument.market), pl.lit(instrument.exchange), pl.lit(instrument.currency)

    if "ts_code" in normalized_df.columns:
        col_ref = pl.col("ts_code")
    elif "symbol" in normalized_df.columns:
        col_ref = pl.col("symbol")
    else:
        market = "CN" if data_source in {"tushare", "lixinger"} else "US"
        exchange = "SOURCE" if data_source in {"tushare", "lixinger"} else "US_EXCHANGE"
        currency = "CNY" if data_source in {"tushare", "lixinger"} else "USD"
        return pl.lit(market), pl.lit(exchange), pl.lit(currency)
    return infer_market_exchange_currency(col_ref, data_source=data_source)
