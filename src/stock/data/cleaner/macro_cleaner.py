"""全球宏观资产日线数据清洗器。"""

from __future__ import annotations

import polars as pl

from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.quality.quarantine import QuarantineStore
from stock.utils.logger import logger


class MacroDataCleaner(GenericCleaner):
    """允许负收益率与负期货价格，并隔离 OHLC 物理异常行。"""

    _REQUIRED_COLUMNS = ("symbol", "trade_date", "open", "high", "low", "close")

    @classmethod
    def _valid_mask(cls, df: pl.DataFrame) -> pl.Expr:
        """返回宏观 OHLC 的有限值与区间关系校验表达式。"""
        if any(column not in df.columns for column in cls._REQUIRED_COLUMNS):
            return pl.lit(value=False)

        finite_values = pl.all_horizontal(
            [
                pl.col(column)
                .cast(pl.Float64, strict=False)
                .is_finite()
                .fill_null(value=False)
                for column in ("open", "high", "low", "close")
            ]
        )
        valid = (
            pl.col("symbol").is_not_null()
            & pl.col("trade_date").is_not_null()
            & finite_values
            & (pl.col("high") >= pl.col("low"))
            & (pl.col("high") >= pl.col("open"))
            & (pl.col("high") >= pl.col("close"))
            & (pl.col("low") <= pl.col("open"))
            & (pl.col("low") <= pl.col("close"))
        )
        if "volume" in df.columns:
            volume = pl.col("volume").cast(pl.Float64, strict=False)
            valid = valid & volume.is_finite().fill_null(value=False) & (volume >= 0)
        return valid

    def clean(self, df: pl.DataFrame) -> pl.DataFrame:
        """清洗宏观 OHLC 并保留合法负值。"""
        if df.is_empty():
            return df
        valid = self._valid_mask(df)
        cleaned = super().clean(df.filter(valid))
        rejected_count = len(df) - len(cleaned)
        if rejected_count:
            logger.warning(f"宏观数据清洗隔离 {rejected_count} 条异常记录")
        return cleaned

    def clean_with_quarantine(
        self,
        df: pl.DataFrame,
        *,
        endpoint: str,
        request_id: str = "",
        data_source: str = "",
        quarantine: object | None = None,
    ) -> pl.DataFrame:
        """清洗宏观数据，并将异常 OHLC 行写入隔离区。"""
        if df.is_empty():
            return df
        valid = self._valid_mask(df)
        rejected = df.filter(~valid)
        cleaned = super().clean(df.filter(valid))
        if rejected.is_empty() or not isinstance(quarantine, QuarantineStore):
            return cleaned
        quarantine.write(
            rejected,
            endpoint=endpoint,
            reason="macro_ohlc_validation_rejected",
            request_id=request_id,
            data_source=data_source,
        )
        return cleaned
