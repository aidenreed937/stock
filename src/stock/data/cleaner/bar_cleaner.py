"""K 线日线数据清洗器实现。"""

import polars as pl

from stock.data.cleaner.base import BaseDataCleaner
from stock.utils.logger import logger


class BarDataCleaner(BaseDataCleaner):
    """日 K 线数据清洗器，负责过滤逻辑错误记录、去重与空值剔除。"""

    def clean(self, df: pl.DataFrame) -> pl.DataFrame:
        """清洗日 K 线行情数据。

        校验规则包括:
        1. 剔除关键列 (symbol, trade_date, close) 包含 null 的记录。
        2. 剔除价格非正值记录 (open, high, low, close <= 0)。
        3. 剔除最高价低于开盘价/收盘价/最低价的异常逻辑记录。
        4. 按 (symbol, trade_date) 组合去重，保留最新一条记录。

        Args:
            df: 原始数据帧。

        Returns:
            pl.DataFrame: 清洗后的合规数据帧。
        """
        if df.is_empty():
            logger.warning("传入待清洗的数据帧为空，跳过清洗")
            return df

        initial_count = len(df)

        # 自动识别列名别名 (支持原始与标准化后的数据帧)
        sym_col = "symbol" if "symbol" in df.columns else ("ts_code" if "ts_code" in df.columns else "code")
        vol_col = "volume" if "volume" in df.columns else ("vol" if "vol" in df.columns else None)

        # 1. 过滤 null 异常记录
        null_subset = [c for c in [sym_col, "trade_date", "close"] if c in df.columns]
        cleaned_df = df.drop_nulls(subset=null_subset)

        # 2. 过滤非正数值 (价格必须 > 0)
        filter_expr = (
            (pl.col("open") > 0)
            & (pl.col("high") > 0)
            & (pl.col("low") > 0)
            & (pl.col("close") > 0)
        )
        if vol_col:
            filter_expr = filter_expr & (pl.col(vol_col) >= 0)

        cleaned_df = cleaned_df.filter(filter_expr)

        # 3. 过滤最高价 < 最低价 或 最高价 < 开盘价/收盘价 的非法物理数据
        cleaned_df = cleaned_df.filter(
            (pl.col("high") >= pl.col("low"))
            & (pl.col("high") >= pl.col("open"))
            & (pl.col("high") >= pl.col("close"))
        )

        # 4. 按交易日与标的代码去重
        if sym_col in cleaned_df.columns and "trade_date" in cleaned_df.columns:
            cleaned_df = cleaned_df.unique(subset=[sym_col, "trade_date"], keep="last")

        final_count = len(cleaned_df)
        dropped_count = initial_count - final_count

        if dropped_count > 0:
            logger.info(f"数据清洗完成: 原始 {initial_count} 条，剔除脏数据 {dropped_count} 条，剩余 {final_count} 条")
        else:
            logger.debug(f"数据清洗完成: 校验 {final_count} 条记录完全合规")

        return cleaned_df
