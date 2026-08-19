"""数据源与接口显式单位标准化器 (Unit Normalizer)。"""

import polars as pl

from stock_core.utils.logger import logger

# 声明不同数据源与 API endpoint 的显式单位转换规则
# 映射：数据源 -> 接口 -> 原始列 -> (目标列, 倍率)
UNIT_CONVERSION_RULES: dict[str, dict[str, dict[str, tuple[str, float]]]] = {
    "tushare": {
        "daily": {
            # TuShare 原始 vol 单位为“手”，amount 单位为“千元”。
            "vol": ("volume", 100.0),
            "amount": ("amount", 1000.0),
        },
        "stock_daily_bar": {
            "vol": ("volume", 100.0),
            "amount": ("amount", 1000.0),
        },
        "daily_basic": {
            # TuShare 原始 total_mv/circ_mv 单位为“万元”。
            "total_mv": ("total_mv", 10000.0),
            "circ_mv": ("circ_mv", 10000.0),
        },
        "moneyflow": {
            "buy_sm_vol": ("buy_sm_vol", 100.0),
            "sell_sm_vol": ("sell_sm_vol", 100.0),
            "buy_md_vol": ("buy_md_vol", 100.0),
            "sell_md_vol": ("sell_md_vol", 100.0),
            "buy_lg_vol": ("buy_lg_vol", 100.0),
            "sell_lg_vol": ("sell_lg_vol", 100.0),
            "buy_elg_vol": ("buy_elg_vol", 100.0),
            "sell_elg_vol": ("sell_elg_vol", 100.0),
            "buy_sm_amount": ("buy_sm_amount", 10000.0),
            "sell_sm_amount": ("sell_sm_amount", 10000.0),
            "buy_md_amount": ("buy_md_amount", 10000.0),
            "sell_md_amount": ("sell_md_amount", 10000.0),
            "buy_lg_amount": ("buy_lg_amount", 10000.0),
            "sell_lg_amount": ("sell_lg_amount", 10000.0),
            "buy_elg_amount": ("buy_elg_amount", 10000.0),
            "sell_elg_amount": ("sell_elg_amount", 10000.0),
            "net_mf_vol": ("net_mf_vol", 100.0),
            "net_mf_amount": ("net_mf_amount", 10000.0),
        },
        "moneyflow_hsgt": {
            "ggt_ss": ("ggt_ss", 1_000_000.0),
            "ggt_sz": ("ggt_sz", 1_000_000.0),
            "hgt": ("hgt", 1_000_000.0),
            "sgt": ("sgt", 1_000_000.0),
            "north_money": ("north_money", 1_000_000.0),
            "south_money": ("south_money", 1_000_000.0),
        },
        "sw_daily": {
            # TuShare 原始 vol 单位为“手”，金额和市值字段单位为“万元”。
            "vol": ("volume", 100.0),
            "amount": ("amount", 10000.0),
            "total_mv": ("total_mv", 10000.0),
            "float_mv": ("float_mv", 10000.0),
        },
        "opt_daily": {
            # TuShare 期权成交金额单位为万元；成交量和持仓量保留为合约数。
            "amount": ("amount", 10000.0),
        },
        "cb_daily": {
            # 可转债行情的成交量为手（1 手 = 10 张），成交金额为万元。
            "vol": ("volume", 10.0),
            "amount": ("amount", 10000.0),
        },
        "block_trade": {
            # 大宗交易成交量为万股，成交金额为万元。
            "vol": ("volume", 10000.0),
            "amount": ("amount", 10000.0),
        },
        "stk_account": {
            # TuShare 股票开户数据的账户数量单位为万户。
            "weekly_new": ("weekly_new", 10000.0),
            "total": ("total", 10000.0),
            "weekly_hold": ("weekly_hold", 10000.0),
            "weekly_trade": ("weekly_trade", 10000.0),
        },
    }
}


class UnitNormalizer:
    """显式单位标准化器，根据 data_source 和 endpoint 执行无歧义的单位倍率转换。"""

    def __init__(self, data_source: str, endpoint: str) -> None:
        """初始化单位标准化器。

        Args:
            data_source: 数据源标识 (如 tushare).
            endpoint: 接口名称 (如 daily, daily_basic).
        """
        self.data_source = data_source.lower()
        self.endpoint = endpoint.lower()
        self.rules = UNIT_CONVERSION_RULES.get(self.data_source, {}).get(self.endpoint, {})

    def normalize_units(self, df: pl.DataFrame) -> pl.DataFrame:
        """根据配置规则对 DataFrame 中的数值列应用单位转换。

        Args:
            df: 原始响应或提取出的 DataFrame。

        Returns:
            pl.DataFrame: 完成单位倍率转换后的 DataFrame。
        """
        if df.is_empty() or not self.rules:
            return df

        normalized, rejected = self.normalize_units_with_quarantine(df)
        if not rejected.is_empty():
            logger.warning(
                f"接口 [{self.data_source}/{self.endpoint}] 存在 {len(rejected)} 条"
                "无法可靠判定单位的记录，已跳过"
            )
        return normalized

    def normalize_units_with_quarantine(
        self, df: pl.DataFrame
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        """标准化单位，并返回无法可靠判定单位的原始记录。

        TuShare 的行情 RAW 历史中存在逐行混合的金额单位。行情数据不能按
        分区或月份整体乘倍率，因此先按血统说明判定，缺少说明时再按
        ``amount / (vol * close)`` 的数量级逐行判定。
        """
        if df.is_empty() or not self.rules:
            return df, df.head(0)

        if self.data_source == "tushare" and self.endpoint in {"daily", "stock_daily_bar"}:
            return self._normalize_tushare_bar_units(df)

        return self._normalize_configured_units(df), df.head(0)

    def _normalize_configured_units(self, df: pl.DataFrame) -> pl.DataFrame:
        """应用没有逐行混合单位的静态转换规则。"""
        expressions: list[pl.Expr] = []

        for raw_col, (target_col, multiplier) in self.rules.items():
            if raw_col in df.columns:
                # 转换类型为 Float64 并乘以倍率
                expr = (pl.col(raw_col).cast(pl.Float64, strict=False) * multiplier).alias(
                    target_col
                )
                expressions.append(expr)

        if not expressions:
            return df

        logger.debug(
            f"接口 [{self.data_source}/{self.endpoint}] 应用单位转换规则: {list(self.rules.keys())}"
        )

        # 应用表达式转换
        transformed = df.with_columns(expressions)

        # 若原始列名与目标列名不同，移除旧原始列
        cols_to_drop = [
            raw_col
            for raw_col, (target_col, _) in self.rules.items()
            if raw_col != target_col and raw_col in transformed.columns
        ]
        if cols_to_drop:
            transformed = transformed.drop(cols_to_drop)

        return transformed

    @staticmethod
    def _infer_tushare_bar_amount_factor(
        work: pl.DataFrame,
    ) -> tuple[pl.DataFrame, str, list[str]]:
        """按血统说明或价格关系推断单行成交额倍率。"""
        ratio_column = "__amount_volume_price_ratio"
        factor_column = "__amount_unit_factor"
        note = (
            pl.col("source_unit_note").cast(pl.Utf8, strict=False).fill_null("").str.to_lowercase()
            if "source_unit_note" in work.columns
            else pl.lit("")
        )
        ratio_expr = (
            pl.col("amount").cast(pl.Float64, strict=False)
            / (
                pl.col("vol").cast(pl.Float64, strict=False)
                * pl.col("close").cast(pl.Float64, strict=False)
            )
            if "close" in work.columns
            else pl.lit(None, dtype=pl.Float64)
        )
        work = work.with_columns(ratio_expr.alias(ratio_column))
        note_is_normalized = note.str.contains("normalized|归一|标准化|already.*yuan|已归一.*元")
        note_is_thousand_yuan = note.str.contains(
            "thousand\\s*yuan|ten-thousand\\s*yuan|千元|万元|千人民币|万人民币"
        )
        inferred_factor = (
            pl.when(note_is_normalized)
            .then(pl.lit(1.0))
            .when(note_is_thousand_yuan)
            .then(pl.lit(1000.0))
            .when(
                (pl.col("amount").cast(pl.Float64, strict=False) == 0)
                & (pl.col("vol").cast(pl.Float64, strict=False) >= 0)
            )
            .then(pl.lit(1000.0))
            .when(pl.col("amount").is_null() & (pl.col("vol").cast(pl.Float64, strict=False) == 0))
            .then(pl.lit(1000.0))
            .when(pl.col(ratio_column).is_between(0.005, 1.0, closed="both"))
            .then(pl.lit(1000.0))
            .when(pl.col(ratio_column).is_between(10.0, 1000.0, closed="both"))
            .then(pl.lit(1.0))
            .otherwise(None)
        )
        if "close" not in work.columns:
            inferred_factor = (
                pl.when(note_is_normalized)
                .then(pl.lit(1.0))
                .when(note_is_thousand_yuan)
                .then(pl.lit(1000.0))
                .otherwise(None)
            )
        return (
            work.with_columns(inferred_factor.alias(factor_column)),
            factor_column,
            [ratio_column, factor_column],
        )

    def _normalize_tushare_bar_units(self, df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
        """逐行处理 TuShare 日线的成交量与成交额单位。"""
        has_raw_volume = "vol" in df.columns
        has_standard_volume = "volume" in df.columns
        has_amount = "amount" in df.columns

        if not has_raw_volume and not has_standard_volume:
            return df, df.head(0)

        work = df.with_row_index("__unit_row")
        helper_columns: list[str] = []
        factor_column = "__amount_unit_factor"

        if has_amount and has_raw_volume:
            work, factor_column, helper_columns = self._infer_tushare_bar_amount_factor(work)
        elif has_amount:
            # 没有 vol 时只能是已经含有标准 volume 的数据；不得再按 TuShare
            # 原始成交量规则放大成交额。
            work = work.with_columns(pl.lit(1.0).alias(factor_column))
            helper_columns.append(factor_column)

        if has_amount:
            rejected = work.filter(pl.col(factor_column).is_null())
            work = work.filter(pl.col(factor_column).is_not_null())
        else:
            rejected = work.head(0)

        if has_raw_volume:
            volume_expr = (pl.col("vol").cast(pl.Float64, strict=False) * 100.0).alias("volume")
        else:
            volume_expr = pl.col("volume").cast(pl.Float64, strict=False).alias("volume")

        expressions = [volume_expr]
        if has_amount:
            expressions.append(
                (pl.col("amount").cast(pl.Float64, strict=False) * pl.col(factor_column)).alias(
                    "amount"
                )
            )
        transformed = work.with_columns(expressions)

        if helper_columns:
            transformed = transformed.drop(helper_columns)
            rejected = rejected.drop(helper_columns)
        transformed = transformed.drop("__unit_row")
        rejected = rejected.drop("__unit_row")
        if "vol" in transformed.columns:
            transformed = transformed.drop("vol")

        return transformed, rejected
