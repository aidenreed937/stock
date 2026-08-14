"""动量与反转因子群向量化计算模块。"""

import polars as pl


def calculate_momentum(
    df: pl.DataFrame,
    windows: tuple[int, ...] = (20, 60, 120, 250),
    price_col: str = "close",
) -> pl.DataFrame:
    """计算多周期收益动量因子 (N日收益率: P_t / P_{t-N} - 1)。

    Args:
        df: 包含行情数据的 DataFrame，建议包含 trade_date 与 price_col。
        windows: 收益率统计窗口元组 (默认 20, 60, 120, 250 日)。
        price_col: 价格基准列 (默认 close，支持复权后价格)。

    Returns:
        pl.DataFrame: 追加了 mom_{window}d 列的数据表。
    """
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    exprs = []
    for w in windows:
        col_name = f"mom_{w}d"
        if has_symbol:
            expr = (pl.col(price_col) / pl.col(price_col).shift(w).over("symbol") - 1.0).alias(
                col_name
            )
        else:
            expr = (pl.col(price_col) / pl.col(price_col).shift(w) - 1.0).alias(col_name)
        exprs.append(expr)

    return df.with_columns(exprs)


def calculate_short_term_reversal(
    df: pl.DataFrame,
    window: int = 5,
    price_col: str = "close",
) -> pl.DataFrame:
    """计算短期反转因子 (近 N 日超跌/超涨反向信号)。"""
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    col_name = f"reversal_{window}d"
    if has_symbol:
        expr = -(pl.col(price_col) / pl.col(price_col).shift(window).over("symbol") - 1.0).alias(
            col_name
        )
    else:
        expr = -(pl.col(price_col) / pl.col(price_col).shift(window) - 1.0).alias(col_name)

    return df.with_columns(expr)


def calculate_distance_to_high(
    df: pl.DataFrame,
    window: int = 250,
    price_col: str = "close",
) -> pl.DataFrame:
    """计算距离过去 N 日 (如 52 周) 最高价的相对距离 (Close / Max - 1.0)。"""
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    col_name = f"dist_to_high_{window}d"
    if has_symbol:
        rolling_max = pl.col(price_col).rolling_max(window_size=window).over("symbol")
    else:
        rolling_max = pl.col(price_col).rolling_max(window_size=window)

    expr = (pl.col(price_col) / rolling_max - 1.0).alias(col_name)
    return df.with_columns(expr)


def calculate_ema_spread(
    df: pl.DataFrame,
    fast: int = 10,
    slow: int = 60,
    price_col: str = "close",
) -> pl.DataFrame:
    """计算快慢均线相对发散度 ((EMA_fast - EMA_slow) / EMA_slow)。"""
    if df.is_empty() or price_col not in df.columns:
        return df

    has_symbol = "symbol" in df.columns
    col_name = f"ema_spread_{fast}_{slow}"
    if has_symbol:
        fast_ema = pl.col(price_col).ewm_mean(span=fast, adjust=False).over("symbol")
        slow_ema = pl.col(price_col).ewm_mean(span=slow, adjust=False).over("symbol")
    else:
        fast_ema = pl.col(price_col).ewm_mean(span=fast, adjust=False)
        slow_ema = pl.col(price_col).ewm_mean(span=slow, adjust=False)

    expr = ((fast_ema - slow_ema) / slow_ema).alias(col_name)
    return df.with_columns(expr)
