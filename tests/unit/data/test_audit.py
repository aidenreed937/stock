from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl

from stock.data.audit import run_audit, run_audit_range
from stock.data.audit.reconciliation import main as audit_main


def test_run_audit_missing_stock_basic():
    with patch("polars.read_parquet", side_effect=Exception("File not found")):
        res = run_audit(date(2026, 8, 1))
        assert res == {}


def test_run_audit_success():
    stock_basic_df = pl.DataFrame({
        "ts_code": ["600000.SH", "000001.SZ"],
        "name": ["浦发银行", "平安银行"],
        "list_date": ["19991110", "19910403"],
        "delist_date": pl.Series("delist_date", [None, None], dtype=pl.String),
    })
    daily_df = pl.DataFrame({
        "symbol": ["600000.SH"],
        "trade_date": ["2026-08-01"],
        "close": [10.0],
    })

    def mock_read_parquet(pattern: str):
        if "stock_basic" in pattern:
            return stock_basic_df
        return daily_df

    mock_client = MagicMock()
    mock_client.query.return_value = pl.DataFrame({"ts_code": ["000001.SZ"]})

    with (
        patch("polars.read_parquet", side_effect=mock_read_parquet),
        patch("stock.data.audit.reconciliation.TuShareClient", return_value=mock_client),
    ):
        res = run_audit(date(2026, 8, 1))
        assert res["expected"] == 2
        assert res["actual"] == 1
        assert res["suspended"] == 1
        assert res["unexplained"] == 0
        assert res["integrity_rate"] == 100.0


def test_run_audit_range():
    mock_audit_res = {
        "date": date(2026, 8, 1),
        "expected": 2,
        "actual": 2,
        "suspended": 0,
        "unexplained": 0,
        "integrity_rate": 100.0,
        "unexplained_symbols": [],
    }

    with (
        patch(
            "stock.data.audit.reconciliation.get_trading_calendar",
            return_value=[date(2026, 8, 3), date(2026, 8, 4)],
        ),
        patch("stock.data.audit.reconciliation.run_audit", return_value=mock_audit_res),
    ):
        res = run_audit_range(date(2026, 8, 1), date(2026, 8, 5), max_workers=2)
        assert res["total_days"] == 2
        assert res["perfect_days"] == 2
        assert res["problematic_days"] == 0
        assert res["avg_integrity_rate"] == 100.0


def test_audit_main_cli():
    with (
        patch("sys.argv", ["audit", "--date", "2026-08-01"]),
        patch("stock.data.audit.reconciliation.run_audit") as mock_run,
    ):
        audit_main()
        mock_run.assert_called_once_with(date(2026, 8, 1), data_source="tushare")


def test_audit_main_range_cli():
    with (
        patch(
            "sys.argv",
            ["audit", "--start", "2026-08-01", "--end", "2026-08-05", "--max-workers", "2"],
        ),
        patch("stock.data.audit.reconciliation.run_audit_range") as mock_run_range,
    ):
        audit_main()
        mock_run_range.assert_called_once_with(
            date(2026, 8, 1),
            date(2026, 8, 5),
            data_source="tushare",
            max_workers=2,
            show_details=False,
        )


def test_run_index_audit():
    from stock.data.audit.reconciliation import run_index_audit

    index_df = pl.DataFrame({
        "symbol": ["000001.SH", "399001.SZ"],
        "trade_date": ["2026-08-01", "2026-08-01"],
    })

    with patch("polars.read_parquet", return_value=index_df):
        res = run_index_audit(date(2026, 8, 1), data_source="tushare")
        assert res["date"] == date(2026, 8, 1)
        assert res["actual_count"] == 2
        assert res["integrity_rate"] > 0


def test_run_index_audit_range():
    from stock.data.audit.reconciliation import run_index_audit_range

    mock_res = {
        "date": date(2026, 8, 1),
        "expected_count": 2,
        "actual_count": 2,
        "missing_count": 0,
        "missing_indices": [],
        "integrity_rate": 100.0,
    }

    with (
        patch(
            "stock.data.audit.reconciliation.get_trading_calendar",
            return_value=[date(2026, 8, 1), date(2026, 8, 2)],
        ),
        patch("stock.data.audit.reconciliation.run_index_audit", return_value=mock_res),
    ):
        res = run_index_audit_range(date(2026, 8, 1), date(2026, 8, 2), data_source="tushare")
        assert res["total_days"] == 2
        assert res["perfect_days"] == 2
        assert res["avg_integrity_rate"] == 100.0


def test_audit_main_index_cli():
    with (
        patch("sys.argv", ["audit", "--mode", "index", "--date", "2026-08-01"]),
        patch("stock.data.audit.reconciliation.run_index_audit") as mock_run_index,
    ):
        audit_main()
        mock_run_index.assert_called_once_with(date(2026, 8, 1), data_source="tushare")
