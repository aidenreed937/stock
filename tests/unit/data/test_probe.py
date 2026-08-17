"""GlobalDataProbe 单元测试。"""

from datetime import date
from unittest.mock import MagicMock

import polars as pl
from stock_data.ops.probe import GlobalDataProbe


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


def test_probe_empty_and_error_branches():
    """测试 probe 结果为 EMPTY 与 ERROR/FAILED 时的结果包装。"""
    mock_ts = MagicMock()
    mock_ts.fetch_daily_bars_df.return_value = pl.DataFrame()

    mock_yf = MagicMock()
    mock_yf.fetch_daily_bars_df.side_effect = Exception("API Key Error")

    probe = GlobalDataProbe(tushare_fetcher=mock_ts, yfinance_fetcher=mock_yf)
    results_ts = probe.probe_tushare()
    assert results_ts[0]["status"] == "EMPTY"

    results_yf = probe.probe_yfinance()
    assert results_yf[0]["status"] == "FAILED"
    assert "API Key Error" in results_yf[0]["error"]


def test_probe_main_cli(capsys):
    """测试 probe main CLI 函数能正常打印不同状态输出。"""
    from unittest.mock import patch
    from stock_data.ops.probe import main as probe_main

    mock_probe = MagicMock()
    mock_probe.probe_all.return_value = [
        {"source": "tushare", "endpoint": "daily_bar", "freq": "daily", "status": "SUCCESS", "latency_ms": 12.3, "rows": 100, "cols": 5},
        {"source": "yfinance", "endpoint": "macro", "freq": "daily", "status": "EMPTY", "latency_ms": 50.0},
        {"source": "fred", "endpoint": "cpi", "freq": "monthly", "status": "FAILED", "latency_ms": 5.0, "error": "Unauthorized Token"},
    ]

    with patch("stock_data.ops.probe.GlobalDataProbe", return_value=mock_probe):
        probe_main()

    captured = capsys.readouterr().out
    assert "全数据源 (TuShare, yfinance, FRED, 理杏仁) 健康度与连通性验证报告" in captured
    assert "[OK]   [tushare ] daily_bar" in captured
    assert "[WARN] [yfinance] macro" in captured
    assert "[INFO] [fred    ] cpi" in captured
