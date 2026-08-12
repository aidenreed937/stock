"""通用数据标准化器，适用于非 K 线（如基本面估值、指数基本面等）接口。"""

import polars as pl

from stock.data.normalizer.base import BaseDataNormalizer
from stock.utils.logger import logger


class GenericNormalizer(BaseDataNormalizer):
    """通用数据标准化器，负责日期转换与通用列对齐。"""

    def normalize(self, df: pl.DataFrame) -> pl.DataFrame:
        if df.is_empty():
            return df

        normalized_df = df

        # 1. 重命名 stockCode / code 为 symbol，date 为 trade_date
        rename_dict = {}
        if "stockCode" in normalized_df.columns and "symbol" not in normalized_df.columns:
            rename_dict["stockCode"] = "symbol"
        elif "code" in normalized_df.columns and "symbol" not in normalized_df.columns:
            rename_dict["code"] = "symbol"

        if "date" in normalized_df.columns and "trade_date" not in normalized_df.columns:
            rename_dict["date"] = "trade_date"

        if rename_dict:
            normalized_df = normalized_df.rename(rename_dict)

        # 2. 转换 trade_date 为 Date 类型
        if "trade_date" in normalized_df.columns and normalized_df["trade_date"].dtype == pl.String:
            non_null_vals = normalized_df["trade_date"].drop_nulls()
            if not non_null_vals.is_empty():
                first_val = non_null_vals[0]
                if "T" in first_val:
                    normalized_df = normalized_df.with_columns(
                        pl.col("trade_date").str.slice(0, 10).str.to_date("%Y-%m-%d").alias("trade_date")
                    )
                else:
                    fmt = "%Y%m%d" if len(first_val) == 8 else "%Y-%m-%d"
                    normalized_df = normalized_df.with_columns(
                        pl.col("trade_date").str.to_date(fmt).alias("trade_date")
                    )

        logger.debug(f"通用数据标准化完成，包含列: {normalized_df.columns}")
        return normalized_df
