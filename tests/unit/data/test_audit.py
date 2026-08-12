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

    def mock_read_parquet(pattern):
        pattern_str = str(pattern)
        if "stock_basic" in pattern_str:
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


def test_run_daily_basic_audit():
    from stock.data.audit.reconciliation import run_daily_basic_audit

    bar_df = pl.DataFrame({"symbol": ["600000.SH", "000001.SZ"], "trade_date": ["2026-08-01", "2026-08-01"]})
    db_df = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": ["2026-08-01"]})

    def mock_read(pattern: str):
        if "stock_daily_bar" in pattern:
            return bar_df
        return db_df

    with patch("polars.read_parquet", side_effect=mock_read):
        res = run_daily_basic_audit(date(2026, 8, 1))
        assert res["bar_count"] == 2
        assert res["basic_count"] == 1
        assert res["match_count"] == 1
        assert res["integrity_rate"] == 50.0


def test_run_adj_factor_audit():
    from stock.data.audit.reconciliation import run_adj_factor_audit

    basic_df = pl.DataFrame({"symbol": ["600000.SH", "000001.SZ"], "list_date": ["19991110", "19910403"]})
    adj_df = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": ["2026-08-01"]})

    def mock_read(pattern):
        if isinstance(pattern, list):
            return basic_df
        return adj_df

    with patch("polars.read_parquet", side_effect=mock_read):
        res = run_adj_factor_audit(date(2026, 8, 1))
        assert res["expected_count"] == 2
        assert res["actual_count"] == 1
        assert res["coverage_rate"] == 50.0


def test_run_hk_hold_audit():
    from stock.data.audit.reconciliation import run_hk_hold_audit

    hk_df = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": ["2026-08-01"], "vol": [100000.0]})

    with patch("polars.read_parquet", return_value=hk_df):
        res = run_hk_hold_audit(date(2026, 8, 1))
        assert res["symbols_count"] == 1
        assert res["total_vol"] == 100000.0


def test_run_sw_industry_audit():
    from stock.data.audit import run_sw_industry_audit

    const_df = pl.DataFrame({"symbol": ["110000", "210000"]})
    fund_df = pl.DataFrame({"symbol": ["110000"], "trade_date": ["2026-08-01"]})

    def mock_read(pattern: str):
        if "sw_2021_constituents" in pattern:
            return const_df
        return fund_df

    with patch("polars.read_parquet", side_effect=mock_read):
        res = run_sw_industry_audit(date(2026, 8, 1))
        assert res["constituents_industry_count"] == 2
        assert res["actual_industry_count"] == 1
