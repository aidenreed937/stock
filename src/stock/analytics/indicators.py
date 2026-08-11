import polars as pl


def calculate_sma(df: pl.DataFrame, window: int = 5, column: str = "close") -> pl.DataFrame:
    """计算简单移动平均线 (Simple Moving Average)"""
    sma_col_name = f"sma_{window}"
    return df.with_columns(
        pl.col(column).rolling_mean(window_size=window).alias(sma_col_name)
    )


def calculate_ema(df: pl.DataFrame, window: int = 12, column: str = "close") -> pl.DataFrame:
    """计算指数移动平均线 (Exponential Moving Average)"""
    ema_col_name = f"ema_{window}"
    return df.with_columns(
        pl.col(column).ewm_mean(span=window, adjust=False).alias(ema_col_name)
    )


def calculate_rsi(df: pl.DataFrame, window: int = 14, column: str = "close") -> pl.DataFrame:
    """计算相对强弱指标 (RSI)"""
    diff = pl.col(column).diff()
    gain = pl.when(diff > 0).then(diff).otherwise(0.0)
    loss = pl.when(diff < 0).then(-diff).otherwise(0.0)

    avg_gain = gain.ewm_mean(span=window, adjust=False)
    avg_loss = loss.ewm_mean(span=window, adjust=False)

    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))

    return df.with_columns(rsi.alias(f"rsi_{window}"))
