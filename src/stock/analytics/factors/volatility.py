"""波动率与风险因子群向量化计算模块。"""

import polars as pl


def calculate_realized_volatility(
    df: pl.DataFrame,
    windows: tuple[int, ...] = (20, 60),
    price_col: str = "close",
    annual_days: int = 252,
) -> pl.DataFrame:
    """计算年化已实现历史波动率 (Realized Volatility)。

    公式: Std(ln(P_t / P_{t-1}), window) * sqrt(annual_days)
    """
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    if has_symbol:
        log_ret = (
            (pl.col(price_col) / pl.col(price_col).shift(1).over("symbol")).log().alias("_log_ret")
        )
    else:
        log_ret = (pl.col(price_col) / pl.col(price_col).shift(1)).log().alias("_log_ret")

    temp_df = df.with_columns(log_ret)
    sqrt_days = annual_days**0.5

    exprs = []
    for w in windows:
        col_name = f"realized_vol_{w}d"
        if has_symbol:
            expr = (pl.col("_log_ret").rolling_std(window_size=w).over("symbol") * sqrt_days).alias(
                col_name
            )
        else:
            expr = (pl.col("_log_ret").rolling_std(window_size=w) * sqrt_days).alias(col_name)
        exprs.append(expr)

    return temp_df.with_columns(exprs).drop("_log_ret")


def calculate_atr(
    df: pl.DataFrame,
    window: int = 20,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> pl.DataFrame:
    """计算真实波幅指标 (ATR, Average True Range) 及相对 ATR 比率。"""
    required = {high_col, low_col, close_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    has_symbol = "symbol" in df.columns
    if has_symbol:
        prev_close = pl.col(close_col).shift(1).over("symbol")
    else:
        prev_close = pl.col(close_col).shift(1)

    tr1 = pl.col(high_col) - pl.col(low_col)
    tr2 = (pl.col(high_col) - prev_close).abs()
    tr3 = (pl.col(low_col) - prev_close).abs()

    tr = pl.max_horizontal(tr1, tr2, tr3).alias("_tr")
    temp_df = df.with_columns(tr)

    atr_col = f"atr_{window}d"
    ratio_col = f"atr_ratio_{window}d"

    if has_symbol:
        atr_expr = pl.col("_tr").rolling_mean(window_size=window).over("symbol").alias(atr_col)
    else:
        atr_expr = pl.col("_tr").rolling_mean(window_size=window).alias(atr_col)

    temp_df = temp_df.with_columns(atr_expr)
    ratio_expr = (pl.col(atr_col) / pl.col(close_col)).alias(ratio_col)

    return temp_df.with_columns(ratio_expr).drop("_tr")


def calculate_bollinger_bandwidth(
    df: pl.DataFrame,
    window: int = 20,
    num_std: float = 2.0,
    price_col: str = "close",
) -> pl.DataFrame:
    """计算布林带相对宽度 (Bollinger BandWidth: 4 * std / MA)。"""
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    col_name = f"bollinger_bandwidth_{window}d"

    if has_symbol:
        ma = pl.col(price_col).rolling_mean(window_size=window).over("symbol")
        std = pl.col(price_col).rolling_std(window_size=window).over("symbol")
    else:
        ma = pl.col(price_col).rolling_mean(window_size=window)
        std = pl.col(price_col).rolling_std(window_size=window)

    expr = (num_std * 2.0 * std / (ma + 1e-8)).alias(col_name)
    return df.with_columns(expr)
