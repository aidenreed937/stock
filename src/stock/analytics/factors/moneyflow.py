"""资金流与主力博弈因子群向量化计算模块。"""

import polars as pl


def calculate_main_moneyflow_factors(
    df: pl.DataFrame,
    windows: tuple[int, ...] = (5, 20),
    amount_col: str = "amount",
    net_mf_col: str = "net_mf_amount",
) -> pl.DataFrame:
    """计算主力资金净流入占比及多周期滚动平均因子。

    公式: Main_Inflow_Ratio = Net_MF_Amount / (Amount + 1e-6)
    """
    required = {amount_col, net_mf_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    has_symbol = "symbol" in df.columns
    daily_ratio = (pl.col(net_mf_col) / (pl.col(amount_col) + 1.0)).alias("main_inflow_ratio")
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
    rzrqye_col: str = "rzrqye",
    rzmre_col: str = "rzmre",
    total_amount_col: str = "amount",
) -> pl.DataFrame:
    """计算两融杠杆交易活跃度与两融余额动量因子。"""
    if df.is_empty() or rzrqye_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    exprs = []

    # 1. 融资买入额占总成交额比率
    if rzmre_col in df.columns and total_amount_col in df.columns:
        exprs.append(
            (pl.col(rzmre_col) / (pl.col(total_amount_col) + 1.0)).alias("margin_trading_share")
        )

    # 2. 两融余额多周期动量增长率
    for w in windows:
        col_name = f"margin_growth_{w}d"
        if has_symbol:
            expr = (pl.col(rzrqye_col) / pl.col(rzrqye_col).shift(w).over("symbol") - 1.0).alias(
                col_name
            )
        else:
            expr = (pl.col(rzrqye_col) / pl.col(rzrqye_col).shift(w) - 1.0).alias(col_name)
        exprs.append(expr)

    return df.with_columns(exprs)
