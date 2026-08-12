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

# 内部统一 Schema 标准列顺序
STANDARD_COLUMNS = [
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
]


class BarDataNormalizer(BaseDataNormalizer):
    """日 K 线数据标准化器，负责列名别名对齐、日期格式统一与标准列排序。"""

    def normalize(self, df: pl.DataFrame) -> pl.DataFrame:
        """标准化日 K 线行情数据帧。

        转换操作包括:
        1. 别名对齐: 将 ts_code/code 重命名为 symbol，vol 重命名为 volume，date 重命名为 trade_date。
        2. 数据类型转换: 确保 trade_date 转换为 Date 类型，价格列转换为 Float64。
        3. 标准列筛选与排序: 保证返回的数据结构符合 DailyBar 统一约定。

        Args:
            df: 经过 Cleaner 处理的数据帧。

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

        # 2. 转换 trade_date 为 Date 类型（自动适应 YYYYMMDD 与 YYYY-MM-DD 各种格式）
        if "trade_date" in normalized_df.columns and normalized_df["trade_date"].dtype == pl.String:
            non_null_vals = normalized_df["trade_date"].drop_nulls()
            if not non_null_vals.is_empty():
                first_val = non_null_vals[0]
                fmt = "%Y%m%d" if len(first_val) == 8 else "%Y-%m-%d"
                normalized_df = normalized_df.with_columns(
                    pl.col("trade_date").str.to_date(fmt).alias("trade_date")
                )

        # 3. 按统一的标准列名过滤并排序
        existing_std_cols = [c for c in STANDARD_COLUMNS if c in normalized_df.columns]
        other_cols = [c for c in normalized_df.columns if c not in STANDARD_COLUMNS]

        normalized_df = normalized_df.select(existing_std_cols + other_cols)
        logger.debug(f"数据标准化完成，包含列: {normalized_df.columns}")

        return normalized_df
