"""GlobalDataProbe 单元测试。"""

from datetime import date
from unittest.mock import MagicMock

import polars as pl
from stock.data.probe import GlobalDataProbe


def test_global_probe_tushare():
    mock_ts = MagicMock()
    mock_df = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": ["2026-08-11"], "close": [10.0]})
    mock_ts.fetch_daily_bars_df.return_value = mock_df

    probe = GlobalDataProbe(tushare_fetcher=mock_ts)
    results = probe.probe_tushare()

    assert len(results) == 2
    assert results[0]["status"] == "SUCCESS"
    assert results[0]["source"] == "tushare"


def test_global_probe_yfinance():
    mock_yf = MagicMock()
    mock_df = pl.DataFrame({"symbol": ["AAPL"], "close": [220.0]})
    mock_yf.fetch_daily_bars_df.return_value = mock_df
    mock_yf.fetch_index_valuations_df.return_value = mock_df
    mock_yf.fetch_macro_indicators_df.return_value = mock_df

    probe = GlobalDataProbe(yfinance_fetcher=mock_yf)
    results = probe.probe_yfinance()

    assert len(results) == 4
    assert all(r["status"] == "SUCCESS" for r in results)


def test_global_probe_fred():
    mock_fred = MagicMock()
    mock_df = pl.DataFrame({"symbol": ["CPIAUCSL"], "value": [300.0]})
    mock_fred.fetch_series_df.return_value = mock_df

    probe = GlobalDataProbe(fred_fetcher=mock_fred)
    results = probe.probe_fred()

    assert len(results) == 3
    assert all(r["status"] == "SUCCESS" for r in results)


def test_global_probe_all():
    mock_ts = MagicMock()
    mock_yf = MagicMock()
    mock_fred = MagicMock()
    mock_lix = MagicMock()

    mock_df = pl.DataFrame({"symbol": ["TEST"], "value": [1.0]})
    mock_ts.fetch_daily_bars_df.return_value = mock_df
    mock_yf.fetch_daily_bars_df.return_value = mock_df
    mock_yf.fetch_index_valuations_df.return_value = mock_df
    mock_yf.fetch_macro_indicators_df.return_value = mock_df
    mock_fred.fetch_series_df.return_value = mock_df
    mock_lix.fetch_daily_bars_df.return_value = mock_df

    probe = GlobalDataProbe(
        tushare_fetcher=mock_ts,
        yfinance_fetcher=mock_yf,
        fred_fetcher=mock_fred,
        lixinger_fetcher=mock_lix,
    )
    results = probe.probe_all()
    assert len(results) == 10
