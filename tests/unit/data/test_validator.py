"""OfflineDataValidator 单元测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
from stock.data.validator import OfflineDataValidator


def test_audit_daily_bars_passed():
    mock_store = MagicMock()
    mock_df = pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ"],
        "trade_date": [date(2026, 8, 11), date(2026, 8, 11)],
        "open": [10.0, 20.0],
        "high": [10.5, 20.5],
        "low": [9.8, 19.8],
        "close": [10.2, 20.2],
        "pre_close": [10.0, 20.0],
        "pct_chg": [2.0, 1.0],
    })
    mock_store.query_history.return_value = mock_df

    validator = OfflineDataValidator(store=mock_store)
    report = validator.audit_daily_bars()

    assert report["total_records"] == 2
    assert report["duplicate_records"] == 0
    assert report["total_nulls"] == 0
    assert report["physical_errors"] == 0


def test_audit_daily_bars_empty():
    mock_store = MagicMock()
    mock_store.query_history.return_value = pl.DataFrame()

    validator = OfflineDataValidator(store=mock_store)
    report = validator.audit_daily_bars()

    assert report["status"] == "EMPTY"


def test_audit_daily_bars_with_nulls_and_calc_diff():
    mock_store = MagicMock()
    mock_df = pl.DataFrame({
        "symbol": ["000001.SZ", "000001.SZ"],  # Duplicate symbol on same date
        "trade_date": [date(2026, 8, 11), date(2026, 8, 11)],
        "open": [10.0, 20.0],
        "high": [10.5, 20.5],
        "low": [9.8, 19.8],
        "close": [10.2, None],  # One null close
        "pre_close": [10.0, 20.0],
        "pct_chg": [10.0, 1.0],  # 10.0% is diff from (10.2-10)/10*100=2.0%
    })
    mock_store.query_history.return_value = mock_df

def test_validator_main(monkeypatch):
    import sys
    from stock.data.validator import main
    mock_store = MagicMock()
    mock_df = pl.DataFrame({
        "symbol": ["000001.SZ"],
        "trade_date": [date(2026, 8, 11)],
        "open": [10.0],
        "high": [10.5],
        "low": [9.8],
        "close": [10.2],
        "pre_close": [10.0],
        "pct_chg": [2.0],
    })
    mock_store.query_history.return_value = mock_df

    monkeypatch.setattr(sys, "argv", ["validator"])
    monkeypatch.setattr("stock.data.validator.DuckDBMarketStore", lambda: mock_store)
    main()


def test_validator_main_empty(monkeypatch, capsys):
    import sys
    from stock.data.validator import main

    mock_store = MagicMock()
    mock_store.query_history.return_value = pl.DataFrame()

    monkeypatch.setattr(sys, "argv", ["validator", "--endpoint", "daily"])
    monkeypatch.setattr("stock.data.validator.DuckDBMarketStore", lambda: mock_store)
    main()

    captured = capsys.readouterr().out
    assert "[WARN] 未检测到任何本地落盘数据！" in captured


def test_validator_entrypoint(monkeypatch):
    import runpy

    with patch("stock.data.validator.main") as mock_main:
        runpy.run_module("stock.data.validator", run_name="__main__")
        mock_main.assert_called_once()
