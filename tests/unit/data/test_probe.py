"""TuShareProbe 单元测试。"""

from datetime import date
from unittest.mock import MagicMock

import polars as pl
from stock.data.probe import TuShareProbe


def test_probe_endpoint_success():
    mock_fetcher = MagicMock()
    mock_df = pl.DataFrame({"ts_code": ["600519.SH"], "trade_date": ["20260811"], "close": [1500.0]})
    mock_fetcher.fetch_daily_bars_df.return_value = mock_df

    probe = TuShareProbe(fetcher=mock_fetcher)
    res = probe.probe_endpoint("daily", start_date=date(2026, 8, 11), end_date=date(2026, 8, 11))

    assert res["status"] == "SUCCESS"
    assert res["rows"] == 1
    assert "ts_code" in res["columns"]


def test_probe_trade_cal_success():
    mock_fetcher = MagicMock()
    mock_fetcher.fetch_trade_cal.return_value = [date(2026, 8, 11)]

    probe = TuShareProbe(fetcher=mock_fetcher)
    res = probe.probe_endpoint("trade_cal")

    assert res["status"] == "SUCCESS"
    assert res["rows"] == 1


def test_probe_endpoint_error():
    mock_fetcher = MagicMock()
    mock_fetcher.fetch_daily_bars_df.side_effect = Exception("Connection refused")

    probe = TuShareProbe(fetcher=mock_fetcher)
    res = probe.probe_endpoint("daily")

    assert res["status"] == "FAILED"
    assert "Connection refused" in res["error"]
