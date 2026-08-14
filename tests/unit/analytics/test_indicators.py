from datetime import date, timedelta

import polars as pl

from stock.analytics.indicators import calculate_ema, calculate_rsi, calculate_sma


def test_calculate_indicators() -> None:
    # 构造 30 天的基础行情序列
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(30)]
    prices = [10.0 + (i * 0.5 if i % 2 == 0 else -i * 0.3) for i in range(30)]
    df = pl.DataFrame(
        {
            "symbol": ["TEST"] * 30,
            "trade_date": dates,
            "open": prices,
            "high": [p + 0.5 for p in prices],
            "low": [p - 0.5 for p in prices],
            "close": prices,
            "volume": [1000.0] * 30,
            "amount": [p * 1000.0 for p in prices],
        }
    )
    assert len(df) > 20

    df_sma = calculate_sma(df, window=5)
    assert "sma_5" in df_sma.columns
    # 前 4 行均值为 None/null
    assert df_sma["sma_5"][4] is not None

    df_ema = calculate_ema(df, window=12)
    assert "ema_12" in df_ema.columns

    df_rsi = calculate_rsi(df, window=14)
    assert "rsi_14" in df_rsi.columns
    # RSI 值应该在 0 到 100 之间
    valid_rsi = df_rsi["rsi_14"].drop_nulls()
    assert (valid_rsi >= 0).all()
    assert (valid_rsi <= 100).all()
