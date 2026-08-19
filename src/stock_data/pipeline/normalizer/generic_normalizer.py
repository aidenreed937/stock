"""通用数据标准化器，适用于非 K 线（如基本面估值、指数基本面等）接口。"""

from collections.abc import Sequence

import polars as pl

from stock_core.utils.logger import logger
from stock_data.pipeline.cleaner.date_utils import parse_mixed_date
from stock_data.pipeline.normalizer.base import BaseDataNormalizer


class GenericNormalizer(BaseDataNormalizer):
    """通用数据标准化器，负责日期转换与通用列对齐。"""

    def __init__(self, date_columns: Sequence[str] | None = None) -> None:
        """初始化标准化器。"""
        self.date_columns = tuple(date_columns or ())

    def normalize(self, df: pl.DataFrame) -> pl.DataFrame:
        if df.is_empty():
            return df

        normalized_df = df

        # 1. 统一标的与日期列名；历史数据可能同时包含标准列和源端别名。
        # ts_code/stockCode 是权威标识，code 只用于填充缺失的标准标识。
        for alias in ("ts_code", "stockCode"):
            if alias not in normalized_df.columns:
                continue
            if "symbol" not in normalized_df.columns:
                normalized_df = normalized_df.rename({alias: "symbol"})
            else:
                normalized_df = normalized_df.with_columns(
                    pl.coalesce(
                        [
                            pl.col(alias).cast(pl.Utf8, strict=False),
                            pl.col("symbol").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("symbol")
                ).drop(alias)

        if "code" in normalized_df.columns:
            if "symbol" not in normalized_df.columns:
                normalized_df = normalized_df.rename({"code": "symbol"})
            else:
                normalized_df = normalized_df.with_columns(
                    pl.coalesce(
                        [
                            pl.col("symbol").cast(pl.Utf8, strict=False),
                            pl.col("code").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("symbol")
                ).drop("code")

        for alias in ("date", "Date"):
            if alias not in normalized_df.columns:
                continue
            if "trade_date" not in normalized_df.columns:
                normalized_df = normalized_df.rename({alias: "trade_date"})
            else:
                normalized_df = normalized_df.with_columns(
                    pl.coalesce(
                        [
                            pl.col("trade_date").cast(pl.Utf8, strict=False),
                            pl.col(alias).cast(pl.Utf8, strict=False),
                        ]
                    ).alias("trade_date")
                ).drop(alias)

        if "asOfDate" in normalized_df.columns:
            if "as_of_date" not in normalized_df.columns:
                normalized_df = normalized_df.rename({"asOfDate": "as_of_date"})
            else:
                normalized_df = normalized_df.with_columns(
                    pl.coalesce(
                        [
                            pl.col("as_of_date").cast(pl.Utf8, strict=False),
                            pl.col("asOfDate").cast(pl.Utf8, strict=False),
                        ]
                    ).alias("as_of_date")
                ).drop("asOfDate")

        # 2. 转换注册契约声明的业务日期为 Date 类型
        date_columns = list(dict.fromkeys((*self.date_columns, "trade_date", "as_of_date")))
        for date_column in date_columns:
            if date_column in {"month", "quarter"}:
                continue
            if date_column in normalized_df.columns:
                normalized_df = normalized_df.with_columns(
                    parse_mixed_date(date_column).alias(date_column)
                )

        # 3. 移除历史明细记录统计字段 (若存在)
        for legacy_col in ("raw_row_count", "clean_row_count"):
            if legacy_col in normalized_df.columns:
                normalized_df = normalized_df.drop(legacy_col)

        logger.debug(f"通用数据标准化完成，包含列: {normalized_df.columns}")
        return normalized_df
