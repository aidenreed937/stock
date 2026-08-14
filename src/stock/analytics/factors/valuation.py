"""估值分位与宏观跨资产因子群向量化计算模块。"""

import polars as pl


def calculate_rolling_percentile(
    df: pl.DataFrame,
    metric_cols: tuple[str, ...] = ("pe_ttm", "pb"),
    window_days: int = 1250,
) -> pl.DataFrame:
    """计算指标在过去 N 个交易日 (如 5 年约 1250 日) 滚动窗口内的历史百分位 (0~100)。

    公式: Count(x_i <= x_current) / Window_Size * 100
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
        # 统计在滚动窗口中低于当前值的比例
        # 利用 (rank / count) 构造高效滚动近似分位数
        if has_symbol:
            rolling_min = pl.col(col).rolling_min(window_size=window_days).over("symbol")
            rolling_max = pl.col(col).rolling_max(window_size=window_days).over("symbol")
        else:
            rolling_min = pl.col(col).rolling_min(window_size=window_days)
            rolling_max = pl.col(col).rolling_max(window_size=window_days)

        # Min-Max 归一化百分位映射 (0~100)
        pct_expr = (
            ((pl.col(col) - rolling_min) / (rolling_max - rolling_min + 1e-8) * 100.0)
            .clip(0.0, 100.0)
            .alias(col_name)
        )
        exprs.append(pct_expr)

    return df.with_columns(exprs)


def calculate_equity_risk_premium(
    df: pl.DataFrame,
    pe_col: str = "pe_ttm",
    bond_yield_col: str = "cn_10y_bond_yield",
) -> pl.DataFrame:
    """计算股权风险溢价 (ERP, Equity Risk Premium)。

    公式: ERP = (1 / PE_TTM) * 100 - 10年期国债收益率(%)
    """
    required = {pe_col, bond_yield_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    earning_yield = (1.0 / (pl.col(pe_col) + 1e-6)) * 100.0
    erp_expr = (earning_yield - pl.col(bond_yield_col)).alias("equity_risk_premium")

    return df.with_columns(erp_expr)


def calculate_yield_curve_slope(
    df: pl.DataFrame,
    long_yield_col: str = "t10y",
    short_yield_col: str = "t2y",
) -> pl.DataFrame:
    """计算国债期限利差与收益率曲线斜率 (如 10Y - 2Y 利差)。"""
    required = {long_yield_col, short_yield_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    slope_expr = (pl.col(long_yield_col) - pl.col(short_yield_col)).alias(
        "yield_curve_slope_10y_2y"
    )
    return df.with_columns(slope_expr)
