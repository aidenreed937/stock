"""流动性与微观结构因子群向量化计算模块。"""

import polars as pl


def calculate_amihud_illiquidity(
    df: pl.DataFrame,
    window: int = 20,
    price_col: str = "close",
    amount_col: str = "amount",
    scale_factor: float = 1e8,
) -> pl.DataFrame:
    """计算 Amihud 非流动性因子 (Amihud Illiquidity Ratio)。

    公式: Mean(|R_t| / Amount_t, window) * scale_factor
    数值越大代表单位资金冲击引发的价格偏离越大，即流动性越差。
    """
    required = {price_col, amount_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    has_symbol = "symbol" in df.columns
    if has_symbol:
        ret = (pl.col(price_col) / pl.col(price_col).shift(1).over("symbol") - 1.0).abs()
    else:
        ret = (pl.col(price_col) / pl.col(price_col).shift(1) - 1.0).abs()

    illiq_daily = (ret / (pl.col(amount_col) + 1.0) * scale_factor).alias("_daily_illiq")
    temp_df = df.with_columns(illiq_daily)

    col_name = f"amihud_illiq_{window}d"
    if has_symbol:
        expr = (
            pl.col("_daily_illiq").rolling_mean(window_size=window).over("symbol").alias(col_name)
        )
    else:
        expr = pl.col("_daily_illiq").rolling_mean(window_size=window).alias(col_name)

    return temp_df.with_columns(expr).drop("_daily_illiq")


def calculate_turnover_factors(
    df: pl.DataFrame,
    window: int = 20,
    turnover_col: str = "turnover_rate",
) -> pl.DataFrame:
    """计算换手率均值与换手率波动率因子。"""
    if df.is_empty() or turnover_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    mean_col = f"turnover_mean_{window}d"
    std_col = f"turnover_std_{window}d"

    if has_symbol:
        mean_expr = (
            pl.col(turnover_col).rolling_mean(window_size=window).over("symbol").alias(mean_col)
        )
        std_expr = (
            pl.col(turnover_col).rolling_std(window_size=window).over("symbol").alias(std_col)
        )
    else:
        mean_expr = pl.col(turnover_col).rolling_mean(window_size=window).alias(mean_col)
        std_expr = pl.col(turnover_col).rolling_std(window_size=window).alias(std_col)

    return df.with_columns([mean_expr, std_expr])


def calculate_volume_surprise(
    df: pl.DataFrame,
    short_window: int = 5,
    long_window: int = 20,
    vol_col: str = "volume",
) -> pl.DataFrame:
    """计算量能突增异动因子 (短周期均量 / 长周期基准均量 - 1.0)。"""
    if df.is_empty() or vol_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    col_name = f"volume_surprise_{short_window}_{long_window}"

    if has_symbol:
        short_vol = pl.col(vol_col).rolling_mean(window_size=short_window).over("symbol")
        long_vol = pl.col(vol_col).rolling_mean(window_size=long_window).over("symbol")
    else:
        short_vol = pl.col(vol_col).rolling_mean(window_size=short_window)
        long_vol = pl.col(vol_col).rolling_mean(window_size=long_window)

    expr = (short_vol / (long_vol + 1e-6) - 1.0).alias(col_name)
    return df.with_columns(expr)
