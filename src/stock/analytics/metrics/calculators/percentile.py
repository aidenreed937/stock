"""滚动分位指标的共用计算工具。"""

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


def rolling_percentile(column: str, output: str, window: int) -> pl.Expr:
    """构造允许历史缺失值的滚动分位表达式。"""
    return (
        pl.col(column)
        .rolling_map(
            lambda values: percentile_rank(values, window),
            window_size=window,
            min_samples=1,
        )
        .alias(output)
    )
