"""资金流与主力博弈因子群向量化计算原语。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars。
"""

from __future__ import annotations

import polars as pl


def calculate_main_moneyflow_factors(
    df: pl.DataFrame,
    windows: tuple[int, ...] = (5, 20),
    amount_col: str = "amount",
    net_mf_col: str = "net_mf_amount",
) -> pl.DataFrame:
    """计算主力资金净流入占比及多周期滚动平均因子。

    公式: Main_Inflow_Ratio = Net_MF_Amount / Amount（Amount <= 0 时缺失）
    """
    required = {amount_col, net_mf_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    has_symbol = "symbol" in df.columns
    daily_ratio = (
        pl.when(pl.col(amount_col) > 0)
        .then(pl.col(net_mf_col) / pl.col(amount_col))
        .otherwise(None)
        .alias("main_inflow_ratio")
    )
    temp_df = df.with_columns(daily_ratio)

    exprs = []
    for w in windows:
        col_name = f"main_inflow_ratio_{w}d"
        if has_symbol:
            expr = (
                pl.col("main_inflow_ratio")
                .rolling_mean(window_size=w)
                .over("symbol")
                .alias(col_name)
            )
        else:
            expr = pl.col("main_inflow_ratio").rolling_mean(window_size=w).alias(col_name)
        exprs.append(expr)

    return temp_df.with_columns(exprs)


def calculate_margin_factors(
    df: pl.DataFrame,
    windows: tuple[int, ...] = (5, 20),
    margin_buy_col: str = "rzmre",
    margin_balance_col: str = "rzrqye",
    amount_col: str = "amount",
) -> pl.DataFrame:
    """计算融资融券交易活跃度与余额变动因子。"""
    required = {margin_buy_col, amount_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    has_symbol = "symbol" in df.columns
    margin_ratio = (
        pl.when(pl.col(amount_col) > 0)
        .then(pl.col(margin_buy_col) / pl.col(amount_col))
        .otherwise(None)
        .alias("margin_trading_share")
    )
    temp_df = df.with_columns(margin_ratio)

    if margin_balance_col in df.columns:
        exprs = []
        for w in windows:
            col_name = f"margin_growth_{w}d"
            if has_symbol:
                expr = (
                    (
                        pl.col(margin_balance_col)
                        / pl.col(margin_balance_col).shift(w).over("symbol")
                        - 1.0
                    )
                    * 100.0
                ).alias(col_name)
            else:
                expr = (
                    (pl.col(margin_balance_col) / pl.col(margin_balance_col).shift(w) - 1.0) * 100.0
                ).alias(col_name)
            exprs.append(expr)
        temp_df = temp_df.with_columns(exprs)

    return temp_df


__all__ = [
    "calculate_main_moneyflow_factors",
    "calculate_margin_factors",
]
