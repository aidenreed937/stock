"""通用数据清洗器实现。"""

import polars as pl

from stock_core.utils.logger import logger
from stock_data.pipeline.cleaner.base import BaseDataCleaner

LIXINGER_INDEX_FUNDAMENTAL_METRICS = (
    "pe_ttm.ew",
    "pe_ttm.mcw",
    "pb.ew",
    "pb.mcw",
    "ps_ttm.ew",
    "ps_ttm.mcw",
    "dyr.ew",
    "dyr.mcw",
    "mc",
)


def filter_lixinger_index_fundamental_placeholders(
    df: pl.DataFrame,
) -> tuple[pl.DataFrame, int]:
    """过滤 LiXinger 指数估值接口返回的全指标为空占位行。"""
    metric_columns = [
        column for column in LIXINGER_INDEX_FUNDAMENTAL_METRICS if column in df.columns
    ]
    if df.is_empty() or not metric_columns:
        return df, 0

    placeholder = pl.all_horizontal([pl.col(column).is_null() for column in metric_columns])
    filtered = df.filter(~placeholder)
    return filtered, len(df) - len(filtered)


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
                elif k in ("ts_code", "stockCode", "code") and "symbol" in cleaned_df.columns:
                    target_keys.append("symbol")
                elif k in ("trade_date", "date") and "trade_date" in cleaned_df.columns:
                    target_keys.append("trade_date")
                elif k in ("trade_date", "date") and "date" in cleaned_df.columns:
                    target_keys.append("date")
                elif k == "as_of_date" and "asOfDate" in cleaned_df.columns:
                    target_keys.append("asOfDate")
        else:
            # 默认推理主键：综合考虑所有实体列与期间列
            entity_cols = [
                c
                for c in [
                    "index_code",
                    "con_code",
                    "industry_code",
                    "symbol",
                    "ts_code",
                    "stockCode",
                    "code",
                    "exchange_id",
                ]
                if c in cleaned_df.columns
            ]
            period_cols = [
                c
                for c in [
                    "trade_date",
                    "date",
                    "month",
                    "quarter",
                    "end_date",
                    "as_of_date",
                    "asOfDate",
                    "in_date",
                    "out_date",
                    "suspend_date",
                    "publish_date",
                    "period",
                    "Date",
                    "Start Date",
                ]
                if c in cleaned_df.columns
            ]
            if (
                "index_code" in entity_cols or "con_code" in entity_cols
            ) and "symbol" in entity_cols:
                try:
                    if cleaned_df["symbol"].n_unique() <= 1:
                        entity_cols.remove("symbol")
                except Exception:
                    pass
            target_keys = list(dict.fromkeys(entity_cols + period_cols))

            # 仅在无实体列（纯宏观时间序列）时对 month/quarter 额外修正
            if not entity_cols:
                if "month" in cleaned_df.columns and "month" not in target_keys:
                    target_keys.append("month")
                elif "quarter" in cleaned_df.columns and "quarter" not in target_keys:
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


class LixingerIndexFundamentalCleaner(GenericCleaner):
    """清洗 LiXinger 指数估值数据并剔除非交易日空指标占位行。"""

    def clean(self, df: pl.DataFrame) -> pl.DataFrame:
        """过滤全指标为空的占位行，再执行通用主键清洗。"""
        filtered, placeholder_count = filter_lixinger_index_fundamental_placeholders(df)
        if placeholder_count:
            logger.info(
                f"LiXinger 指数估值清洗完成: 过滤 {placeholder_count} 条非交易日空指标占位行"
            )
        return super().clean(filtered)
