"""估值与风险溢价原子计算原语 (Valuation & Risk Premium Primitives)。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars 与标准库。
包含股债比 (EY/BY)、股权风险溢价 (ERP)、股息利差及估值滚动分位数等向量化算子。
"""

from __future__ import annotations

import polars as pl


def calculate_equity_risk_premium(
    df: pl.DataFrame,
    pe_col: str = "pe_ttm",
    bond_yield_col: str = "cn_10y_bond_yield",
    erp_col_name: str = "equity_risk_premium",
) -> pl.DataFrame:
    """计算股权风险溢价 (ERP, Equity Risk Premium)。

    公式: ERP = (1 / PE_TTM) * 100 - 10年期国债收益率(%)
    """
    required = {pe_col, bond_yield_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    earning_yield = (1.0 / (pl.col(pe_col) + 1e-6)) * 100.0
    erp_expr = (earning_yield - pl.col(bond_yield_col)).alias(erp_col_name)

    return df.with_columns(erp_expr)


def calculate_ey_by_ratio(
    df: pl.DataFrame,
    pe_col: str = "pe_ttm",
    bond_yield_col: str = "cn_10y_bond_yield",
    ey_by_col_name: str = "ey_by_ratio",
) -> pl.DataFrame:
    """计算股债收益比 (EY/BY Ratio: 股票盈利收益率 / 国债收益率)。

    公式: EY/BY = (1 / PE) / (Bond_Yield / 100) = (100 / PE) / Bond_Yield
    """
    required = {pe_col, bond_yield_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    earning_yield = (1.0 / (pl.col(pe_col) + 1e-6)) * 100.0
    ey_by_expr = (earning_yield / (pl.col(bond_yield_col) + 1e-6)).alias(ey_by_col_name)

    return df.with_columns(ey_by_expr)


def calculate_dividend_spread(
    df: pl.DataFrame,
    dividend_yield_col: str = "dv_ratio",
    bond_yield_col: str = "cn_10y_bond_yield",
    spread_col_name: str = "dividend_bond_spread",
) -> pl.DataFrame:
    """计算股息利差 (Dividend Yield Spread)。

    公式: Spread = 股息率(%) - 10年期国债收益率(%)
    """
    required = {dividend_yield_col, bond_yield_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    spread_expr = (pl.col(dividend_yield_col) - pl.col(bond_yield_col)).alias(spread_col_name)
    return df.with_columns(spread_expr)


def calculate_rolling_percentile(
    df: pl.DataFrame,
    metric_cols: tuple[str, ...] = ("pe_ttm", "pb"),
    window_days: int = 1250,
) -> pl.DataFrame:
    """计算估值指标在过去 N 个交易日 (如 5 年约 1250 日) 滚动窗口内的历史百分位 (0~100)。

    公式: (x_t - Rolling_Min) / (Rolling_Max - Rolling_Min) * 100
    """
    if df.is_empty():
        return df

    valid_cols = [c for c in metric_cols if c in df.columns]
    if not valid_cols:
        return df

    has_symbol = "symbol" in df.columns
    exprs = []

    for col in valid_cols:
        col_name = f"{col}_percentile_{window_days}d"
        if has_symbol:
            rolling_min = pl.col(col).rolling_min(window_size=window_days).over("symbol")
            rolling_max = pl.col(col).rolling_max(window_size=window_days).over("symbol")
        else:
            rolling_min = pl.col(col).rolling_min(window_size=window_days)
            rolling_max = pl.col(col).rolling_max(window_size=window_days)

        pct_expr = (
            ((pl.col(col) - rolling_min) / (rolling_max - rolling_min + 1e-8) * 100.0)
            .clip(0.0, 100.0)
            .alias(col_name)
        )
        exprs.append(pct_expr)

    return df.with_columns(exprs)


__all__ = [
    "calculate_dividend_spread",
    "calculate_equity_risk_premium",
    "calculate_ey_by_ratio",
    "calculate_rolling_percentile",
]
