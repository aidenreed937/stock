"""波动率与风险因子群向量化计算原语。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars。
"""

from __future__ import annotations

import polars as pl

from stock_analytics.primitives.indicators import _wilder_mean


def calculate_realized_volatility(
    df: pl.DataFrame,
    windows: tuple[int, ...] = (20, 60),
    price_col: str = "close",
    annual_days: int = 252,
    *,
    as_percentage: bool = False,
) -> pl.DataFrame:
    """计算年化已实现历史波动率 (Realized Volatility)。

    公式: Std(ln(P_t / P_{t-1}), window) * sqrt(annual_days)
    默认输出小数制 (如 0.25 代表 25% 年化波动率)，与 metrics.calculators 体系严格对齐。
    若 as_percentage=True 则输出百分数制 (如 25.0)。
    """
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    if has_symbol:
        log_ret = (
            (pl.col(price_col) / pl.col(price_col).shift(1).over("symbol")).log().alias("_log_ret")
        )
    else:
        log_ret = (pl.col(price_col) / pl.col(price_col).shift(1)).log().alias("_log_ret")

    temp_df = df.with_columns(log_ret)
    exprs = []
    annual_factor = annual_days**0.5
    multiplier = 100.0 if as_percentage else 1.0

    for w in windows:
        col_name = f"realized_vol_{w}d"
        if has_symbol:
            expr = (
                pl.col("_log_ret").rolling_std(window_size=w).over("symbol")
                * (annual_factor * multiplier)
            ).alias(col_name)
        else:
            expr = (
                pl.col("_log_ret").rolling_std(window_size=w) * (annual_factor * multiplier)
            ).alias(col_name)
        exprs.append(expr)

    return temp_df.with_columns(exprs).drop("_log_ret")


def calculate_atr(
    df: pl.DataFrame,
    window: int = 14,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> pl.DataFrame:
    """计算真实波幅与平均真实波幅 (ATR, Average True Range)。

    公式: TR = Max(H - L, |H - C_{t-1}|, |L - C_{t-1}|)
          ATR = Wilder(TR, window)，首个窗口使用 SMA 作为种子
    """
    required = {high_col, low_col, close_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    has_symbol = "symbol" in df.columns
    if has_symbol:
        prev_close = pl.col(close_col).shift(1).over("symbol")
    else:
        prev_close = pl.col(close_col).shift(1)

    hl = pl.col(high_col) - pl.col(low_col)
    hpc = (pl.col(high_col) - prev_close).abs()
    lpc = (pl.col(low_col) - prev_close).abs()

    tr_expr = (
        pl.when(prev_close.is_null())
        .then(hl)
        .otherwise(pl.max_horizontal(hl, hpc, lpc))
        .alias("_tr")
    )
    temp_df = df.with_columns(tr_expr)

    atr_name = f"atr_{window}d"
    natr_name = f"atr_ratio_{window}d"

    temp_df = _wilder_mean(temp_df, "_tr", window, atr_name)

    natr_expr = (
        pl.when(pl.col(close_col) > 0)
        .then(pl.col(atr_name) / pl.col(close_col) * 100.0)
        .otherwise(None)
        .alias(natr_name)
    )
    return temp_df.with_columns(natr_expr).drop("_tr")


def calculate_bollinger_bandwidth(
    df: pl.DataFrame,
    window: int = 20,
    num_std: float = 2.0,
    price_col: str = "close",
) -> pl.DataFrame:
    """计算布林带相对宽度与价格分位数 (%B)。

    公式: Bandwidth = (Upper - Lower) / Middle * 100
          %B = (Close - Lower) / (Upper - Lower)
    """
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    if has_symbol:
        rolling_mean = pl.col(price_col).rolling_mean(window_size=window).over("symbol")
        rolling_std = pl.col(price_col).rolling_std(window_size=window).over("symbol")
    else:
        rolling_mean = pl.col(price_col).rolling_mean(window_size=window)
        rolling_std = pl.col(price_col).rolling_std(window_size=window)

    upper = rolling_mean + (rolling_std * num_std)
    lower = rolling_mean - (rolling_std * num_std)

    bandwidth = ((upper - lower) / (rolling_mean + 1e-8) * 100.0).alias(
        f"bollinger_bandwidth_{window}d"
    )
    percent_b = ((pl.col(price_col) - lower) / (upper - lower + 1e-8)).alias(
        f"bollinger_percent_b_{window}d"
    )

    return df.with_columns([bandwidth, percent_b])


__all__ = [
    "calculate_atr",
    "calculate_bollinger_bandwidth",
    "calculate_realized_volatility",
]
