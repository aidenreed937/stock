"""通用 Polars 向量化表达式规则 (Expression Rules)。

包含跨面板个股/标的时序与截面纯表达式构造函数 (无状态、纯 Polars Expr)。
零外部业务依赖，可被特征工程 (Features)、指标体系 (Metrics) 与模型层共同复用。
"""

from __future__ import annotations

from math import ceil

import polars as pl

_MIN_VALID_RATIO = 0.8


# ==========================================
# 1. 市场宽度与个股面板时序规则 (Breadth Rules)
# ==========================================


def daily_return(column: str = "close", output: str | None = None) -> pl.Expr:
    """个股日收益率（收盘价环比 - 1）。"""
    return (pl.col(column) / pl.col(column).shift(1).over("symbol") - 1.0).alias(
        output or f"{column}_return_1d"
    )


def above_ma(column: str = "close", window: int = 20, output: str | None = None) -> pl.Expr:
    """个股收盘价是否站上 N 日均线（均线未成型时为 None）。"""
    return (pl.col(column) > pl.col(column).rolling_mean(window).over("symbol")).alias(
        output or f"{column}_above_ma{window}"
    )


def at_rolling_high(column: str = "close", window: int = 252, output: str | None = None) -> pl.Expr:
    """个股收盘价是否处于 N 日窗口最高点。"""
    return (pl.col(column) >= pl.col(column).rolling_max(window).over("symbol")).alias(
        output or f"{column}_high_{window}d"
    )


def at_rolling_low(column: str = "close", window: int = 252, output: str | None = None) -> pl.Expr:
    """个股收盘价是否处于 N 日窗口最低点。"""
    return (pl.col(column) <= pl.col(column).rolling_min(window).over("symbol")).alias(
        output or f"{column}_low_{window}d"
    )


def share(count_col: str, total_col: str, output: str) -> pl.Expr:
    """分子占分母之比，分母非正时为 None。"""
    return (
        pl.when(pl.col(total_col) > 0)
        .then(pl.col(count_col) / pl.col(total_col))
        .otherwise(None)
        .alias(output)
    )


# ==========================================
# 2. 滚动统计与分位数规则 (Rolling Rules)
# ==========================================


def percentile_rank(
    values: pl.Series,
    window: int,
    *,
    current: float | int | None = None,
) -> float | None:
    """按升序最小名次计算当前值的历史分位。"""
    if window < 1:
        raise ValueError("window must be positive")
    if values.is_empty():
        return None
    valid_values = values.drop_nulls()
    if len(valid_values) < ceil(window * _MIN_VALID_RATIO):
        return None
    current_value = values[-1] if current is None else current
    if current_value is None or len(valid_values) <= 1:
        return None
    rank_min = sum(value < current_value for value in valid_values)
    return float(rank_min) / (len(valid_values) - 1) * 100.0


def rolling_percentile(column: str, window: int, output: str | None = None) -> pl.Expr:
    """构造允许历史缺失值的滚动分位表达式。"""
    min_valid_samples = ceil(window * _MIN_VALID_RATIO)
    valid_count = (
        pl.col(column)
        .is_not_null()
        .cast(pl.UInt32)
        .rolling_sum(
            window_size=window,
            min_samples=1,
        )
    )
    rank = pl.col(column).rolling_rank(
        window_size=window,
        method="min",
        min_samples=1,
    )
    return (
        pl.when(
            pl.col(column).is_not_null() & (valid_count >= min_valid_samples) & (valid_count > 1)
        )
        .then((rank.cast(pl.Float64) - 1.0) / (valid_count.cast(pl.Float64) - 1.0) * 100.0)
        .otherwise(None)
        .alias(output or f"{column}_percentile_{window}d")
    )


def rolling_zscore(
    column: str,
    window: int,
    output: str | None = None,
    *,
    min_samples: int | None = None,
) -> pl.Expr:
    """构造滚动 Z 分数表达式，标准差为 0 或样本不足时为 None。"""
    mean = pl.col(column).rolling_mean(window_size=window, min_samples=min_samples)
    std = pl.col(column).rolling_std(window_size=window, min_samples=min_samples)
    return (
        pl.when(std > 0)
        .then((pl.col(column) - mean) / std)
        .otherwise(None)
        .alias(output or f"{column}_zscore_{window}d")
    )


def growth(column: str, window: int, output: str | None = None) -> pl.Expr:
    """构造 N 期增长率表达式（当期 / N 期前 - 1）。"""
    return (pl.col(column) / pl.col(column).shift(window) - 1.0).alias(
        output or f"{column}_growth_{window}d"
    )


__all__ = [
    "above_ma",
    "at_rolling_high",
    "at_rolling_low",
    "daily_return",
    "growth",
    "percentile_rank",
    "rolling_percentile",
    "rolling_zscore",
    "share",
]
