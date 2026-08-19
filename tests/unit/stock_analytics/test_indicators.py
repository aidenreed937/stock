from datetime import date, timedelta

import polars as pl
import pytest

from stock_analytics.primitives.indicators import (
    DEFAULT_EMA_WINDOW,
    DEFAULT_MACD_FAST,
    DEFAULT_MACD_SIGNAL,
    DEFAULT_MACD_SLOW,
    DEFAULT_RSI_WINDOW,
    DEFAULT_SMA_WINDOW,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
)
from stock_analytics.primitives.volatility import calculate_atr


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

    df_sma = calculate_sma(df, window=DEFAULT_SMA_WINDOW)
    assert "sma_5" in df_sma.columns
    # 前 4 行均值为 None/null
    assert df_sma["sma_5"][4] is not None

    df_ema = calculate_ema(df, window=DEFAULT_EMA_WINDOW)
    assert "ema_12" in df_ema.columns

    df_rsi = calculate_rsi(df, window=DEFAULT_RSI_WINDOW)
    assert "rsi_14" in df_rsi.columns
    # RSI 值应该在 0 到 100 之间
    valid_rsi = df_rsi["rsi_14"].drop_nulls()
    assert (valid_rsi >= 0).all()
    assert (valid_rsi <= 100).all()

    df_macd = calculate_macd(
        df, fast=DEFAULT_MACD_FAST, slow=DEFAULT_MACD_SLOW, signal=DEFAULT_MACD_SIGNAL
    )
    assert "macd" in df_macd.columns
    assert "macd_signal" in df_macd.columns
    assert "macd_hist" in df_macd.columns


def test_indicator_safety_guards() -> None:
    empty_df = pl.DataFrame()
    assert calculate_sma(empty_df).is_empty()
    assert calculate_ema(empty_df).is_empty()
    assert calculate_rsi(empty_df).is_empty()
    assert calculate_macd(empty_df).is_empty()

    missing_col_df = pl.DataFrame({"volume": [100.0, 200.0]})
    assert "sma_5" not in calculate_sma(missing_col_df, column="close").columns
    assert "ema_12" not in calculate_ema(missing_col_df, column="close").columns
    assert "rsi_14" not in calculate_rsi(missing_col_df, column="close").columns
    assert "macd" not in calculate_macd(missing_col_df, column="close").columns


def test_rsi_matches_wilder_reference_vector() -> None:
    prices = [
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        46.08,
        45.89,
        46.03,
        45.61,
        46.28,
        46.28,
        46.00,
        46.03,
        46.41,
        46.22,
        45.64,
        46.21,
    ]

    result = calculate_rsi(pl.DataFrame({"close": prices}), window=14)

    assert result["rsi_14"][14] == pytest.approx(70.4641350211)


def test_atr_matches_wilder_seed_and_recursion() -> None:
    frame = pl.DataFrame(
        {
            "high": [10.0, 11.0, 12.0, 13.0],
            "low": [8.0, 9.0, 9.0, 10.0],
            "close": [9.0, 10.0, 11.0, 12.0],
        }
    )

    result = calculate_atr(frame, window=3)

    assert result["atr_3d"].to_list()[:2] == [None, None]
    assert result["atr_3d"][2] == pytest.approx(7.0 / 3.0)
    assert result["atr_3d"][3] == pytest.approx((7.0 / 3.0 * 2.0 + 3.0) / 3.0)
