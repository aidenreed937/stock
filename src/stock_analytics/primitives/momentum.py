"""动量与反转因子群向量化计算原语。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars。
"""

from __future__ import annotations

import polars as pl


def calculate_momentum(
    df: pl.DataFrame,
    windows: tuple[int, ...] = (20, 60, 120, 250),
    price_col: str = "close",
) -> pl.DataFrame:
    """计算多周期收益动量因子 (N日收益率: P_t / P_{t-N} - 1)。"""
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    exprs = []

    for w in windows:
        col_name = f"mom_{w}d"
        if has_symbol:
            expr = (
                (pl.col(price_col) / pl.col(price_col).shift(w).over("symbol") - 1.0) * 100.0
            ).alias(col_name)
        else:
            expr = ((pl.col(price_col) / pl.col(price_col).shift(w) - 1.0) * 100.0).alias(col_name)
        exprs.append(expr)

    return df.with_columns(exprs)


def calculate_short_term_reversal(
    df: pl.DataFrame,
    window: int = 5,
    price_col: str = "close",
) -> pl.DataFrame:
    """计算短期反转因子 (价格上涨时反转因子为负)。

    公式: Reversal = - (P_t / P_{t-N} - 1) * 100
    """
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    col_name = f"reversal_{window}d"
    if has_symbol:
        expr = (
            -1.0
            * (pl.col(price_col) / pl.col(price_col).shift(window).over("symbol") - 1.0)
            * 100.0
        ).alias(col_name)
    else:
        expr = (-1.0 * (pl.col(price_col) / pl.col(price_col).shift(window) - 1.0) * 100.0).alias(
            col_name
        )

    return df.with_columns(expr)


def calculate_distance_to_high(
    df: pl.DataFrame,
    window: int = 250,
    price_col: str = "close",
) -> pl.DataFrame:
    """计算距离过去 N 日最高价的距离 (Drawdown from High, 负值表示回撤深度)。

    公式: (P_t - Max(P, window)) / Max(P, window) * 100
    """
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    if has_symbol:
        rolling_max = pl.col(price_col).rolling_max(window_size=window).over("symbol")
    else:
        rolling_max = pl.col(price_col).rolling_max(window_size=window)

    dist_expr = ((pl.col(price_col) - rolling_max) / (rolling_max + 1e-8) * 100.0).alias(
        f"dist_to_high_{window}d"
    )
    return df.with_columns(dist_expr)


def calculate_ema_spread(
    df: pl.DataFrame,
    fast: int = 12,
    slow: int = 26,
    price_col: str = "close",
) -> pl.DataFrame:
    """计算快慢均线偏离扩散因子 (类似 MACD DIF 相对强弱)。

    公式: (EMA_fast - EMA_slow) / EMA_slow * 100
    """
    if df.is_empty() or price_col not in df.columns:
        return df

    fast_ema = pl.col(price_col).ewm_mean(span=fast, adjust=False)
    slow_ema = pl.col(price_col).ewm_mean(span=slow, adjust=False)
    spread_expr = ((fast_ema - slow_ema) / (slow_ema + 1e-8) * 100.0).alias(
        f"ema_spread_{fast}_{slow}"
    )

    return df.with_columns(spread_expr)


__all__ = [
    "calculate_distance_to_high",
    "calculate_ema_spread",
    "calculate_momentum",
    "calculate_short_term_reversal",
]
