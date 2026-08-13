"""通用数据清洗器实现。"""

import polars as pl

from stock.data.cleaner.base import BaseDataCleaner
from stock.utils.logger import logger


class GenericCleaner(BaseDataCleaner):
    """通用数据清洗器，适用于非 K 线行情接口（如每日指标、财报、股票基础列表等）。

    只针对指定的 Primary Keys 进行空值过滤与唯一性去重，保留所有合法负数与特定业务字段。
    """

    def __init__(self, primary_keys: list[str] | None = None) -> None:
        """初始化 GenericCleaner。

        Args:
            primary_keys: 主键列表。若为 None，默认尝试使用 symbol/ts_code 与 trade_date/end_date。
        """
        self.primary_keys = primary_keys

    def clean(self, df: pl.DataFrame) -> pl.DataFrame:
        """清洗通用接口数据。

        校验规则包括:
        1. 检查并剔除主键列 (Primary Keys) 包含 null 的记录。
        2. 按主键列组合去重，保留最新一条记录。

        Args:
            df: 待清洗的原始数据帧。

        Returns:
            pl.DataFrame: 清洗后的合规数据帧。
        """
        if df.is_empty():
            logger.warning("传入待清洗的数据帧为空，跳过清洗")
            return df

        initial_count = len(df)
        cleaned_df = df

        # 确定生效的主键列
        target_keys: list[str] = []
        if self.primary_keys:
            for k in self.primary_keys:
                if k in cleaned_df.columns:
                    target_keys.append(k)
                elif k == "ts_code" and "symbol" in cleaned_df.columns:
                    target_keys.append("symbol")
                elif k == "trade_date" and "date" in cleaned_df.columns:
                    target_keys.append("date")
        else:
            # 默认推理主键
            for candidate in ["symbol", "ts_code", "trade_date", "end_date", "date"]:
                if candidate in cleaned_df.columns:
                    target_keys.append(candidate)

        # 月频/季频宏观接口必须保留业务周期；没有 symbol 的数据不能按日期之外的
        # 通用推断键压成单行。
        if "month" in cleaned_df.columns:
            target_keys = [key for key in target_keys if key not in {"symbol", "ts_code", "date"}]
            target_keys.append("month")
        elif "quarter" in cleaned_df.columns:
            target_keys = [key for key in target_keys if key not in {"symbol", "ts_code", "date"}]
            target_keys.append("quarter")

        # 1. 过滤主键包含 null 的记录
        if target_keys:
            cleaned_df = cleaned_df.drop_nulls(subset=target_keys)

        # 2. 主键组合去重
        if target_keys:
            cleaned_df = cleaned_df.unique(subset=target_keys, keep="last")

        final_count = len(cleaned_df)
        dropped_count = initial_count - final_count

        if dropped_count > 0:
            logger.info(
                f"通用数据清洗完成: 原始 {initial_count} 条，剔除脏/重复数据 {dropped_count} 条，剩余 {final_count} 条"
            )
        else:
            logger.debug(f"通用数据清洗完成: 校验 {final_count} 条记录完全合规")

        return cleaned_df
