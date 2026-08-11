from datetime import date

from stock.analytics.indicators import calculate_ema, calculate_rsi, calculate_sma
from stock.data.fetcher.example import MockDataFetcher


def test_calculate_indicators(mock_fetcher: MockDataFetcher) -> None:
    df = mock_fetcher.fetch_daily_bars_df("TEST", date(2026, 1, 1), date(2026, 3, 1))
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
