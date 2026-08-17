"""市场宽度面板规则：个股收益率、均线站上、创新高新低与占比。

宽度规则作用于个股面板（含 symbol 列），滚动窗口按标的独立计算，
因此表达式中已内嵌 .over("symbol")。
"""

import polars as pl


def daily_return(column: str, output: str | None = None) -> pl.Expr:
    """个股日收益率（收盘价环比 - 1）。"""
    return (pl.col(column) / pl.col(column).shift(1).over("symbol") - 1.0).alias(
        output or f"{column}_return_1d"
    )


def above_ma(column: str, window: int, output: str | None = None) -> pl.Expr:
    """个股收盘价是否站上 N 日均线（均线未成型时为 None）。"""
    return (pl.col(column) > pl.col(column).rolling_mean(window).over("symbol")).alias(
        output or f"{column}_above_ma{window}"
    )


def at_rolling_high(column: str, window: int, output: str | None = None) -> pl.Expr:
    """个股收盘价是否处于 N 日窗口最高点。"""
    return (pl.col(column) >= pl.col(column).rolling_max(window).over("symbol")).alias(
        output or f"{column}_high_{window}d"
    )


def at_rolling_low(column: str, window: int, output: str | None = None) -> pl.Expr:
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
