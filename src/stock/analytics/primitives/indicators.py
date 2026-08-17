"""基础量化技术指标原子算子 (EMA, MACD, RSI, SMA)。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars。
"""

from __future__ import annotations

import polars as pl

# 默认技术指标周期常量
DEFAULT_SMA_WINDOW: int = 5
DEFAULT_EMA_WINDOW: int = 12
DEFAULT_RSI_WINDOW: int = 14
DEFAULT_MACD_FAST: int = 12
DEFAULT_MACD_SLOW: int = 26
DEFAULT_MACD_SIGNAL: int = 9


def calculate_sma(
    df: pl.DataFrame, window: int = DEFAULT_SMA_WINDOW, column: str = "close"
) -> pl.DataFrame:
    """计算简单移动平均线 (Simple Moving Average)。"""
    sma_col_name = f"sma_{window}"
    return df.with_columns(pl.col(column).rolling_mean(window_size=window).alias(sma_col_name))


def calculate_ema(
    df: pl.DataFrame, window: int = DEFAULT_EMA_WINDOW, column: str = "close"
) -> pl.DataFrame:
    """计算指数移动平均线 (Exponential Moving Average)。"""
    ema_col_name = f"ema_{window}"
    return df.with_columns(pl.col(column).ewm_mean(span=window, adjust=False).alias(ema_col_name))


def calculate_rsi(
    df: pl.DataFrame, window: int = DEFAULT_RSI_WINDOW, column: str = "close"
) -> pl.DataFrame:
    """计算相对强弱指标 (RSI)。"""
    if "trade_date" in df.columns:
        df = df.sort("trade_date")

    diff = pl.col(column).diff()
    gain = pl.when(diff > 0).then(diff).otherwise(0.0)
    loss = pl.when(diff < 0).then(-diff).otherwise(0.0)

    avg_gain = gain.ewm_mean(span=window, adjust=False)
    avg_loss = loss.ewm_mean(span=window, adjust=False)

    rs = avg_gain / (avg_loss + 1e-10)
    # 当连续平盘 (avg_gain == 0 且 avg_loss == 0) 时，RSI 应为中性值 50.0
    rsi = pl.when((avg_gain == 0) & (avg_loss == 0)).then(50.0).otherwise(100 - (100 / (1 + rs)))

    return df.with_columns(rsi.alias(f"rsi_{window}"))


def calculate_macd(
    df: pl.DataFrame,
    fast: int = DEFAULT_MACD_FAST,
    slow: int = DEFAULT_MACD_SLOW,
    signal: int = DEFAULT_MACD_SIGNAL,
    column: str = "close",
) -> pl.DataFrame:
    """计算 MACD 指标 (平滑异同移动平均线)。"""
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
