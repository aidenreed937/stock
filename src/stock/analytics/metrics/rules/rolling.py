"""滚动统计规则：Z 分数、历史分位与增长率。

规则均为纯表达式构造函数，返回 polars Expr（分位规则同时提供
Series 级 percentile_rank 供单点取值场景复用）。分组粒度由调用方
通过 .over() 组合，本模块不隐含分组。
"""

from math import ceil

import polars as pl

_MIN_VALID_RATIO = 0.8


def percentile_rank(values: pl.Series, window: int) -> float | None:
    """在允许历史缺失值的前提下计算当前值的历史分位。"""
    if values.is_empty() or values[-1] is None:
        return None
    valid_values = values.drop_nulls()
    if len(valid_values) < ceil(window * _MIN_VALID_RATIO):
        return None
    current = values[-1]
    return float((valid_values <= current).sum()) / len(valid_values) * 100.0


def rolling_percentile(column: str, window: int, output: str | None = None) -> pl.Expr:
    """构造允许历史缺失值的滚动分位表达式。"""
    return (
        pl.col(column)
        .rolling_map(
            lambda values: percentile_rank(values, window),
            window_size=window,
            min_samples=1,
        )
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
