"""基础量化技术指标原子算子 (EMA, MACD, RSI, SMA)。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars。
"""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

# 默认技术指标周期常量
DEFAULT_SMA_WINDOW: int = 5
DEFAULT_EMA_WINDOW: int = 12
DEFAULT_RSI_WINDOW: int = 14
DEFAULT_MACD_FAST: int = 12
DEFAULT_MACD_SLOW: int = 26
DEFAULT_MACD_SIGNAL: int = 9


def _over_symbol(expr: pl.Expr) -> pl.Expr:
    return expr.over("symbol")


def _over_identity(expr: pl.Expr) -> pl.Expr:
    return expr


def calculate_sma(
    df: pl.DataFrame, window: int = DEFAULT_SMA_WINDOW, column: str = "close"
) -> pl.DataFrame:
    """计算简单移动平均线 (Simple Moving Average)。"""
    if df.is_empty() or column not in df.columns:
        return df
    sma_col_name = f"sma_{window}"
    return df.with_columns(pl.col(column).rolling_mean(window_size=window).alias(sma_col_name))


def calculate_ema(
    df: pl.DataFrame, window: int = DEFAULT_EMA_WINDOW, column: str = "close"
) -> pl.DataFrame:
    """计算指数移动平均线 (Exponential Moving Average)。"""
    if df.is_empty() or column not in df.columns:
        return df
    ema_col_name = f"ema_{window}"
    return df.with_columns(pl.col(column).ewm_mean(span=window, adjust=False).alias(ema_col_name))


def _wilder_mean(
    df: pl.DataFrame,
    value_column: str,
    window: int,
    output_column: str,
) -> pl.DataFrame:
    """按 Wilder 口径计算平滑均值，并以首个窗口 SMA 作为递推种子。"""
    if window < 1:
        raise ValueError("window must be positive")
    if value_column not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    over: Callable[[pl.Expr], pl.Expr]
    over = _over_symbol if has_symbol else _over_identity
    seed_column = f"_{output_column}_seed"
    seed_count_column = f"_{output_column}_seed_count"
    input_column = f"_{output_column}_input"
    frame = df.with_columns(
        over(pl.col(value_column).rolling_mean(window_size=window, min_samples=window)).alias(
            seed_column
        )
    )
    frame = frame.with_columns(
        over(pl.col(seed_column).is_not_null().cast(pl.Int8).cum_sum()).alias(seed_count_column)
    ).with_columns(
        pl.when(pl.col(seed_count_column) == 1)
        .then(pl.col(seed_column))
        .when(pl.col(seed_count_column) > 1)
        .then(pl.col(value_column))
        .otherwise(None)
        .alias(input_column)
    )
    smoothed = over(
        pl.col(input_column).ewm_mean(
            alpha=1.0 / window,
            adjust=False,
            ignore_nulls=True,
        )
    )
    return frame.with_columns(smoothed.alias(output_column)).drop(
        [seed_column, seed_count_column, input_column]
    )


def calculate_rsi(
    df: pl.DataFrame, window: int = DEFAULT_RSI_WINDOW, column: str = "close"
) -> pl.DataFrame:
    """计算相对强弱指标 (RSI)。"""
    if df.is_empty() or column not in df.columns:
        return df

    if window < 1:
        raise ValueError("window must be positive")

    has_symbol = "symbol" in df.columns
    diff = pl.col(column).diff()
    if has_symbol:
        diff = diff.over("symbol")
    frame = df.with_columns(
        diff.alias("_rsi_diff"),
    ).with_columns(
        pl.when(pl.col("_rsi_diff").is_null())
        .then(None)
        .when(pl.col("_rsi_diff") > 0)
        .then(pl.col("_rsi_diff"))
        .otherwise(0.0)
        .alias("_rsi_gain"),
        pl.when(pl.col("_rsi_diff").is_null())
        .then(None)
        .when(pl.col("_rsi_diff") < 0)
        .then(-pl.col("_rsi_diff"))
        .otherwise(0.0)
        .alias("_rsi_loss"),
    )
    frame = _wilder_mean(frame, "_rsi_gain", window, "_rsi_avg_gain")
    frame = _wilder_mean(frame, "_rsi_loss", window, "_rsi_avg_loss")

    rs = pl.col("_rsi_avg_gain") / pl.col("_rsi_avg_loss")
    rsi = (
        pl.when(pl.col("_rsi_avg_gain").is_null() | pl.col("_rsi_avg_loss").is_null())
        .then(None)
        .when((pl.col("_rsi_avg_gain") == 0) & (pl.col("_rsi_avg_loss") == 0))
        .then(50.0)
        .when(pl.col("_rsi_avg_loss") == 0)
        .then(100.0)
        .when(pl.col("_rsi_avg_gain") == 0)
        .then(0.0)
        .otherwise(100.0 - (100.0 / (1.0 + rs)))
        .alias(f"rsi_{window}")
    )
    return frame.with_columns(rsi).drop(
        ["_rsi_diff", "_rsi_gain", "_rsi_loss", "_rsi_avg_gain", "_rsi_avg_loss"]
    )


def calculate_macd(
    df: pl.DataFrame,
    fast: int = DEFAULT_MACD_FAST,
    slow: int = DEFAULT_MACD_SLOW,
    signal: int = DEFAULT_MACD_SIGNAL,
    column: str = "close",
) -> pl.DataFrame:
    """计算 MACD 指标 (平滑异同移动平均线)。"""
    if df.is_empty() or column not in df.columns:
        return df

    fast_ema = pl.col(column).ewm_mean(span=fast, adjust=False)
    slow_ema = pl.col(column).ewm_mean(span=slow, adjust=False)
    macd = fast_ema - slow_ema
    macd_signal = macd.ewm_mean(span=signal, adjust=False)
    macd_hist = macd - macd_signal

    return df.with_columns(
        [
            macd.alias("macd"),
            macd_signal.alias("macd_signal"),
            macd_hist.alias("macd_hist"),
        ]
    )


__all__ = [
    "DEFAULT_EMA_WINDOW",
    "DEFAULT_MACD_FAST",
    "DEFAULT_MACD_SIGNAL",
    "DEFAULT_MACD_SLOW",
    "DEFAULT_RSI_WINDOW",
    "DEFAULT_SMA_WINDOW",
    "calculate_ema",
    "calculate_macd",
    "calculate_rsi",
    "calculate_sma",
]
