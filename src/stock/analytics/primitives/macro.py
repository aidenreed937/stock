"""宏观总量、证券化率与利差原语 (Macro Primitives)。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars 与标准库。
涵盖宏观资产容量（证券化率）、收益率曲线斜率及宏观利差等物理指标计算。
"""

from __future__ import annotations

import polars as pl


def calculate_securitization_ratio(
    total_market_cap_yi: float,
    gdp_ttm_yi: float,
) -> float:
    """计算证券化率（巴菲特指标：全市场股票总市值 / GDP TTM）。

    Args:
        total_market_cap_yi: 全市场总市值 (亿元)。
        gdp_ttm_yi: 滚动 4 季度 GDP TTM (亿元)。

    Returns:
        float: 证券化率百分比 (如 97.7 表示 97.7%)。若分母无效则返回 0.0。
    """
    if gdp_ttm_yi <= 0:
        return 0.0
    return (total_market_cap_yi / gdp_ttm_yi) * 100.0


def calculate_yield_curve_slope(
    df: pl.DataFrame,
    long_yield_col: str = "t10y",
    short_yield_col: str = "t2y",
) -> pl.DataFrame:
    """计算国债期限利差与收益率曲线斜率 (如 10Y - 2Y 利差)。

    Args:
        df: 包含长端和短端国债收益率的 DataFrame。
        long_yield_col: 长端国债收益率列名 (默认 "t10y")。
        short_yield_col: 短端国债收益率列名 (默认 "t2y")。

    Returns:
        pl.DataFrame: 附加了 yield_curve_slope_10y_2y 列的 DataFrame。
    """
    required = {long_yield_col, short_yield_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    slope_expr = (pl.col(long_yield_col) - pl.col(short_yield_col)).alias(
        "yield_curve_slope_10y_2y"
    )
    return df.with_columns(slope_expr)


def calculate_macro_spread(
    df: pl.DataFrame,
    higher_rate_col: str,
    lower_rate_col: str,
    spread_col_name: str = "macro_spread",
) -> pl.DataFrame:
    """计算通用宏观利差 (如信用利差、中美利差等)。

    Args:
        df: 包含两列利率数据的 DataFrame。
        higher_rate_col: 目标利率 A 列名。
        lower_rate_col: 基准利率 B 列名。
        spread_col_name: 输出的利差列名。

    Returns:
        pl.DataFrame: 附加了利差列的 DataFrame。
    """
    required = {higher_rate_col, lower_rate_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    spread_expr = (pl.col(higher_rate_col) - pl.col(lower_rate_col)).alias(spread_col_name)
    return df.with_columns(spread_expr)


__all__ = [
    "calculate_macro_spread",
    "calculate_securitization_ratio",
    "calculate_yield_curve_slope",
]
