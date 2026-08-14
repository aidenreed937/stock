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

        # 1. 过滤 null 异常记录 (标的与交易日必须存在)
        null_subset = [c for c in [sym_col, "trade_date"] if c in df.columns]
        cleaned_df = df.drop_nulls(subset=null_subset)

        # 对停牌无成交记录 (vol == 0) 进行合理填充:
        # (a) 若 close 为 0/null 且存在有效 pre_close，用 pre_close 填充 close
        if vol_col and "close" in cleaned_df.columns and "pre_close" in cleaned_df.columns:
            is_susp_no_close = (
                (pl.col(vol_col) == 0)
                & ((pl.col("close") <= 0) | pl.col("close").is_null())
                & (pl.col("pre_close") > 0)
            )
            cleaned_df = cleaned_df.with_columns(
                pl.when(is_susp_no_close)
                .then(pl.col("pre_close"))
                .otherwise(pl.col("close"))
                .alias("close")
            )

        # (b) 若 close > 0，对开高低 0/null 对齐 close，amount 缺失/负值填充 0.0
        if vol_col and "close" in cleaned_df.columns:
            is_suspended = (pl.col(vol_col) == 0) & (pl.col("close") > 0)
            fill_exprs = [
                pl.when(is_suspended & ((pl.col(col) <= 0) | pl.col(col).is_null()))
                .then(pl.col("close"))
                .otherwise(pl.col(col))
                .alias(col)
                for col in ("open", "high", "low")
                if col in cleaned_df.columns
            ]
            if "amount" in cleaned_df.columns:
                fill_exprs.append(
                    pl.when(is_suspended & ((pl.col("amount") < 0) | pl.col("amount").is_null()))
                    .then(pl.lit(0.0))
                    .otherwise(pl.col("amount"))
                    .alias("amount")
                )
            if fill_exprs:
                cleaned_df = cleaned_df.with_columns(fill_exprs)

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

        # 3. 过滤 OHLC 物理逻辑错误数据 (High 必须为最高，Low 必须为最低)
        cleaned_df = cleaned_df.filter(
            (pl.col("high") >= pl.col("low"))
            & (pl.col("high") >= pl.col("open"))
            & (pl.col("high") >= pl.col("close"))
            & (pl.col("low") <= pl.col("open"))
            & (pl.col("low") <= pl.col("close"))
        )

        # 4. 数据故障过滤: 换手率超物理极限 (turnover_rate > 300%)
        if "turnover_rate" in cleaned_df.columns:
            cleaned_df = cleaned_df.filter(pl.col("turnover_rate") <= 300.0)

        # 5. 数据故障过滤: 单日极端飞线跳变 (pct_chg > 1000%，属于典型数据单位错位或误脉冲；排除新股首日合法暴涨)
        if "pct_chg" in cleaned_df.columns:
            cleaned_df = cleaned_df.filter(pl.col("pct_chg").abs() <= 1000.0)

        # 6. 按交易日与标的代码去重 (先对齐日期格式避免 20260812 与 2026-08-12 重复)
        if sym_col in cleaned_df.columns and "trade_date" in cleaned_df.columns:
            from stock.utils.date import parse_mixed_date

            try:
                cleaned_df = (
                    cleaned_df.with_columns(parse_mixed_date("trade_date").alias("_dedup_date"))
                    .unique(subset=[sym_col, "_dedup_date"], keep="last")
                    .drop("_dedup_date")
                )
            except Exception:
                cleaned_df = cleaned_df.unique(subset=[sym_col, "trade_date"], keep="last")

        final_count = len(cleaned_df)
        dropped_count = initial_count - final_count

        if dropped_count > 0:
            logger.info(f"数据清洗完成: 原始 {initial_count} 条，剔除脏数据 {dropped_count} 条，剩余 {final_count} 条")
        else:
            logger.debug(f"数据清洗完成: 校验 {final_count} 条记录完全合规")

        return cleaned_df

    def clean_with_quarantine(
        self,
        df: pl.DataFrame,
        *,
        endpoint: str,
        request_id: str = "",
        data_source: str = "",
        quarantine: object | None = None,
    ) -> pl.DataFrame:
        """清洗并将被过滤记录按原因写入隔离区。"""
        cleaned = self.clean(df)
        if quarantine is not None and len(cleaned) < len(df):
            from stock.data.quality.quarantine import QuarantineStore

            if isinstance(quarantine, QuarantineStore):
                quarantine.write(
                    df.join(cleaned, on=df.columns, how="anti"),
                    endpoint=endpoint,
                    reason="bar_validation_rejected",
                    request_id=request_id,
                    data_source=data_source,
                )
        return cleaned
