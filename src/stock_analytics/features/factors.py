"""统一因子计算与特征工程调度引擎 (FactorEngine)。"""

import polars as pl

from stock_analytics.primitives import (
    calculate_amihud_illiquidity,
    calculate_atr,
    calculate_bollinger_bandwidth,
    calculate_distance_to_high,
    calculate_ema_spread,
    calculate_main_moneyflow_factors,
    calculate_momentum,
    calculate_realized_volatility,
    calculate_rolling_percentile,
    calculate_short_term_reversal,
    calculate_turnover_factors,
    calculate_volume_surprise,
)


class FactorEngine:
    """量化多因子统一计算、截面去极值与标准化引擎。"""

    @staticmethod
    def winsorize(
        df: pl.DataFrame,
        factor_cols: list[str],
        lower_quantile: float = 0.01,
        upper_quantile: float = 0.99,
        group_col: str = "trade_date",
    ) -> pl.DataFrame:
        """对指定因子列进行截面分位数缩尾去极值 (Winsorization)。"""
        if df.is_empty() or not factor_cols:
            return df

        has_group = group_col in df.columns
        exprs = []
        for col in factor_cols:
            if col not in df.columns:
                continue
            if has_group:
                low = pl.col(col).quantile(lower_quantile, interpolation="linear").over(group_col)
                high = pl.col(col).quantile(upper_quantile, interpolation="linear").over(group_col)
            else:
                low = pl.col(col).quantile(lower_quantile, interpolation="linear")
                high = pl.col(col).quantile(upper_quantile, interpolation="linear")
            exprs.append(pl.col(col).clip(low, high).alias(col))

        return df.with_columns(exprs)

    @staticmethod
    def standardize_zscore(
        df: pl.DataFrame,
        factor_cols: list[str],
        group_col: str = "trade_date",
    ) -> pl.DataFrame:
        """对指定因子列执行截面 Z-Score 标准化 ((X - Mean) / Std)。"""
        if df.is_empty() or not factor_cols:
            return df

        has_group = group_col in df.columns
        exprs = []
        for col in factor_cols:
            if col not in df.columns:
                continue
            if has_group:
                mean = pl.col(col).mean().over(group_col)
                std = pl.col(col).std().over(group_col)
            else:
                mean = pl.col(col).mean()
                std = pl.col(col).std()
            exprs.append(((pl.col(col) - mean) / (std + 1e-8)).alias(f"{col}_zscore"))

        return df.with_columns(exprs)

    @classmethod
    def compute_all_factors(
        cls,
        df: pl.DataFrame,
        price_col: str = "close",
        *,
        normalize: bool = False,
    ) -> pl.DataFrame:
        """对日线行情与基本面数据执行全套因子特征提取。

        Args:
            df: 必须包含 trade_date, close 等列的基础数据表。
            price_col: 价格基准列。
            normalize: 是否执行截面 Z-Score 标准化。

        Returns:
            pl.DataFrame: 注入了 20+ 个衍生因子特征的宽表。
        """
        if df.is_empty():
            return df

        # 1. 动量与反转
        res = calculate_momentum(df, price_col=price_col)
        res = calculate_short_term_reversal(res, price_col=price_col)
        res = calculate_distance_to_high(res, price_col=price_col)
        res = calculate_ema_spread(res, price_col=price_col)

        # 2. 波动率与风险
        res = calculate_realized_volatility(res, price_col=price_col)
        res = calculate_atr(res, close_col=price_col)
        res = calculate_bollinger_bandwidth(res, price_col=price_col)

        # 3. 流动性与微观结构
        res = calculate_amihud_illiquidity(res, price_col=price_col)
        res = calculate_turnover_factors(res)
        res = calculate_volume_surprise(res)

        # 4. 资金流与估值
        res = calculate_main_moneyflow_factors(res)
        res = calculate_rolling_percentile(res)

        if normalize:
            computed_factor_cols = [
                c
                for c in res.columns
                if c
                not in {
                    "trade_date",
                    "symbol",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "pre_close",
                }
            ]
            res = FactorEngine.winsorize(res, computed_factor_cols)
            res = FactorEngine.standardize_zscore(res, computed_factor_cols)

        return res
