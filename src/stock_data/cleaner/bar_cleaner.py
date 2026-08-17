"""K 线日线数据清洗器实现。"""

from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

import polars as pl

from stock_core.config.settings import settings
from stock_core.utils.logger import logger
from stock_data.cleaner.base import BaseDataCleaner


class BarDataCleaner(BaseDataCleaner):
    """日 K 线数据清洗器，负责过滤逻辑错误记录、去重与空值剔除。"""

    def __init__(self, listing_dates: Mapping[str, date] | None = None) -> None:
        self.listing_dates = dict(listing_dates or {})

    @staticmethod
    def _date_value(value: object) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip().replace("-", "")
        if len(text) >= 8 and text[:8].isdigit():
            try:
                return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
            except ValueError:
                return None
        return None

    def _exclude_pre_listing(self, df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
        """隔离已知上市日前记录；缺少上市日的标的保留并交由审计提示。"""
        if not self.listing_dates or "trade_date" not in df.columns:
            return df, df.head(0)

        symbol_col = next(
            (
                column
                for column in ("symbol", "stockCode", "ts_code", "code")
                if column in df.columns
            ),
            None,
        )
        if symbol_col is None:
            return df, df.head(0)

        listing_rows = [
            {"__listing_symbol": str(symbol), "__listing_date": listed_date}
            for symbol, value in self.listing_dates.items()
            if (listed_date := self._date_value(value)) is not None
        ]
        if not listing_rows:
            return df, df.head(0)

        from stock_data.cleaner.date_utils import parse_mixed_date

        listing_df = pl.DataFrame(listing_rows)
        indexed = (
            df.with_row_index("__bar_row")
            .with_columns(
                pl.col(symbol_col).cast(pl.Utf8, strict=False).alias("__listing_symbol"),
                parse_mixed_date("trade_date").alias("__bar_date"),
            )
            .join(listing_df, on="__listing_symbol", how="left")
        )
        before_listing = (
            pl.col("__listing_date").is_not_null()
            & pl.col("__bar_date").is_not_null()
            & (pl.col("__bar_date") < pl.col("__listing_date"))
        )
        rejected = indexed.filter(before_listing)
        kept = indexed.filter(~before_listing)
        helper_columns = [
            "__bar_row",
            "__listing_symbol",
            "__bar_date",
            "__listing_date",
        ]
        return kept.drop(helper_columns), rejected.drop(helper_columns)

    @staticmethod
    def load_listing_dates(
        data_source: str = "tushare", curated_root: str | Path | None = None
    ) -> dict[str, date]:
        """从本地 stock_basic 快照加载上市日期，供在线与离线清洗共用。"""
        root = Path(curated_root) if curated_root is not None else settings.curated_data_dir
        path = root / data_source / "market=CN" / "stock_basic" / "data.parquet"
        if not path.exists():
            return {}
        try:
            frame = pl.read_parquet(path)
            if not {"symbol", "list_date"}.issubset(frame.columns):
                return {}
            return {
                str(row["symbol"]): listed
                for row in frame.select(["symbol", "list_date"]).iter_rows(named=True)
                if (listed := BarDataCleaner._date_value(row["list_date"])) is not None
            }
        except Exception as exc:
            logger.warning(f"读取 stock_basic 上市日期失败 [{path}]: {exc}")
            return {}

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
        cleaned_df, _ = self._exclude_pre_listing(df)

        # 自动识别列名别名 (支持原始与标准化后的数据帧)
        sym_col = next(
            (
                col
                for col in ("symbol", "stockCode", "ts_code", "code")
                if col in cleaned_df.columns
            ),
            None,
        )
        vol_col = (
            "volume"
            if "volume" in cleaned_df.columns
            else ("vol" if "vol" in cleaned_df.columns else None)
        )

        # 1. 过滤 null 异常记录 (标的与交易日必须存在)
        null_subset = [c for c in [sym_col, "trade_date"] if c in df.columns]
        cleaned_df = cleaned_df.drop_nulls(subset=null_subset)

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

        # (c) 针对非停牌但 high/low 缺失/非正的记录进行边界补全容错
        cleaned_df = self._impute_missing_high_low(cleaned_df)

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
            cleaned_df = cleaned_df.filter(
                pl.col("turnover_rate").is_null() | (pl.col("turnover_rate") <= 300.0)
            )

        # 5. 极端涨跌保留；上市首日涨跌可能合法，非首日异常由质量审计告警。

        # 6. 按交易日与标的代码去重 (先对齐日期格式避免 20260812 与 2026-08-12 重复)
        if sym_col and sym_col in cleaned_df.columns and "trade_date" in cleaned_df.columns:
            from stock_data.cleaner.date_utils import parse_mixed_date

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
            logger.info(
                f"数据清洗完成: 原始 {initial_count} 条，剔除脏数据 {dropped_count} 条，剩余 {final_count} 条"
            )
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
        from stock_data.quality.quarantine import QuarantineStore

        eligible, pre_listing = self._exclude_pre_listing(df)
        cleaned = self.clean(eligible)
        if isinstance(quarantine, QuarantineStore):
            if not pre_listing.is_empty():
                quarantine.write(
                    pre_listing,
                    endpoint=endpoint,
                    reason="trade_date_before_list_date",
                    request_id=request_id,
                    data_source=data_source,
                )
            if len(cleaned) < len(eligible):
                key_columns = [
                    column
                    for column in (
                        "symbol",
                        "stockCode",
                        "ts_code",
                        "code",
                        "trade_date",
                        "date",
                        "datetime",
                    )
                    if column in eligible.columns and column in cleaned.columns
                ]
                rejected = (
                    eligible.join(cleaned.select(key_columns).unique(), on=key_columns, how="anti")
                    if key_columns
                    else eligible.head(0)
                )
                quarantine.write(
                    rejected,
                    endpoint=endpoint,
                    reason="bar_validation_rejected",
                    request_id=request_id,
                    data_source=data_source,
                )
        return cleaned

    @staticmethod
    def _impute_missing_high_low(df: pl.DataFrame) -> pl.DataFrame:
        """针对非停牌但最高价/最低价缺失的边界异常记录进行补齐容错。

        当 open > 0 且 close > 0 时，若 high 为空或非正，则以 max(open, close) 补齐；
        若 low 为空或非正，则以 min(open, close) 补齐。
        """
        if "open" not in df.columns or "close" not in df.columns:
            return df

        valid_prices = (pl.col("open") > 0) & (pl.col("close") > 0)
        fill_exprs: list[pl.Expr] = []

        if "high" in df.columns:
            fill_exprs.append(
                pl.when(valid_prices & ((pl.col("high") <= 0) | pl.col("high").is_null()))
                .then(pl.max_horizontal("open", "close"))
                .otherwise(pl.col("high"))
                .alias("high")
            )

        if "low" in df.columns:
            fill_exprs.append(
                pl.when(valid_prices & ((pl.col("low") <= 0) | pl.col("low").is_null()))
                .then(pl.min_horizontal("open", "close"))
                .otherwise(pl.col("low"))
                .alias("low")
            )

        if fill_exprs:
            return df.with_columns(fill_exprs)
        return df
