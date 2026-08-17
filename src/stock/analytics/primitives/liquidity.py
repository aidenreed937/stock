"""流动性与微观结构因子群向量化计算原语。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars。
"""

from __future__ import annotations

import polars as pl


def calculate_amihud_illiquidity(
    df: pl.DataFrame,
    window: int = 20,
    price_col: str = "close",
    amount_col: str = "amount",
    scale_factor: float = 1e8,
) -> pl.DataFrame:
    """计算 Amihud 非流动性因子 (Amihud Illiquidity Ratio)。

    公式: Mean(|R_t| / Amount_t, window) * scale_factor
    """
    required = {price_col, amount_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    has_symbol = "symbol" in df.columns
    if has_symbol:
        ret = (pl.col(price_col) / pl.col(price_col).shift(1).over("symbol") - 1.0).abs()
    else:
        ret = (pl.col(price_col) / pl.col(price_col).shift(1) - 1.0).abs()

    daily_impact = ret / (pl.col(amount_col) + 1.0) * scale_factor
    temp_df = df.with_columns(daily_impact.alias("_daily_impact"))

    col_name = f"amihud_illiq_{window}d"
    if has_symbol:
        expr = (
            pl.col("_daily_impact").rolling_mean(window_size=window).over("symbol").alias(col_name)
        )
    else:
        expr = pl.col("_daily_impact").rolling_mean(window_size=window).alias(col_name)

    return temp_df.with_columns(expr).drop("_daily_impact")


def calculate_turnover_factors(
    df: pl.DataFrame,
    window: int | None = None,
    windows: tuple[int, ...] = (5, 20, 60),
    turnover_col: str = "turnover_rate",
) -> pl.DataFrame:
    """计算多周期换手率滚动均值与换手率波动率 (Turnover Volatility)。"""
    if df.is_empty() or turnover_col not in df.columns:
        return df

    target_windows = (window,) if window is not None else windows
    has_symbol = "symbol" in df.columns
    exprs = []

    for w in target_windows:
        mean_col = f"turnover_mean_{w}d"
        std_col = f"turnover_std_{w}d"
        if has_symbol:
            expr_mean = (
                pl.col(turnover_col).rolling_mean(window_size=w).over("symbol").alias(mean_col)
            )
            expr_std = pl.col(turnover_col).rolling_std(window_size=w).over("symbol").alias(std_col)
        else:
            expr_mean = pl.col(turnover_col).rolling_mean(window_size=w).alias(mean_col)
            expr_std = pl.col(turnover_col).rolling_std(window_size=w).alias(std_col)
        exprs.extend([expr_mean, expr_std])

    return df.with_columns(exprs)


def calculate_volume_surprise(
    df: pl.DataFrame,
    short_window: int = 5,
    long_window: int = 20,
    volume_col: str = "volume",
) -> pl.DataFrame:
    """计算成交量突增偏离因子 (Volume Surprise)。

    公式: Mean(Vol, 5) / Mean(Vol, 20) - 1.0
    """
    if df.is_empty() or volume_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    if has_symbol:
        vol_short = pl.col(volume_col).rolling_mean(window_size=short_window).over("symbol")
        vol_long = pl.col(volume_col).rolling_mean(window_size=long_window).over("symbol")
    else:
        vol_short = pl.col(volume_col).rolling_mean(window_size=short_window)
        vol_long = pl.col(volume_col).rolling_mean(window_size=long_window)

    col_name = f"volume_surprise_{short_window}_{long_window}"
    surprise_expr = ((vol_short / (vol_long + 1e-8) - 1.0) * 100.0).alias(col_name)
    return df.with_columns(surprise_expr)


__all__ = [
    "calculate_amihud_illiquidity",
    "calculate_turnover_factors",
    "calculate_volume_surprise",
]
