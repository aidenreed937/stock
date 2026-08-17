from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl

from stock_data.governance.audit import run_audit, run_audit_range
from stock_data.governance.audit.reconciliation import main as audit_main


def test_run_audit_missing_stock_basic():
    with patch("polars.read_parquet", side_effect=Exception("File not found")):
        res = run_audit(date(2026, 8, 1))
        assert res == {}


def test_run_audit_success():
    stock_basic_df = pl.DataFrame(
        {
            "ts_code": ["600000.SH", "000001.SZ"],
            "name": ["浦发银行", "平安银行"],
            "list_date": ["19991110", "19910403"],
            "delist_date": pl.Series("delist_date", [None, None], dtype=pl.String),
        }
    )
    daily_df = pl.DataFrame(
        {
            "symbol": ["600000.SH"],
            "trade_date": ["2026-08-01"],
            "close": [10.0],
        }
    )

    def mock_read_parquet(pattern):
        pattern_str = str(pattern)
        if "stock_basic" in pattern_str:
            return stock_basic_df
        if "suspend_d" in pattern_str:
            return pl.DataFrame()
        return daily_df

    mock_client = MagicMock()
    mock_client.query.return_value = pl.DataFrame({"ts_code": ["000001.SZ"]})

    with (
        patch("polars.read_parquet", side_effect=mock_read_parquet),
        patch("stock_data.governance.audit.reconciliation.TuShareClient", return_value=mock_client),
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
            "stock_data.governance.audit.reconciliation.get_trading_calendar",
            return_value=[date(2026, 8, 3), date(2026, 8, 4)],
        ),
        patch("stock_data.governance.audit.reconciliation.run_audit", return_value=mock_audit_res),
    ):
        res = run_audit_range(date(2026, 8, 1), date(2026, 8, 5), max_workers=2)
        assert res["total_days"] == 2
        assert res["perfect_days"] == 2
        assert res["problematic_days"] == 0
        assert res["avg_integrity_rate"] == 100.0


def test_audit_main_cli():
    with (
        patch("sys.argv", ["audit", "--date", "2026-08-01"]),
        patch("stock_data.governance.audit.reconciliation.run_audit") as mock_run,
    ):
        audit_main()
        mock_run.assert_called_once_with(date(2026, 8, 1), data_source="tushare")


def test_audit_main_range_cli():
    with (
        patch(
            "sys.argv",
            ["audit", "--start", "2026-08-01", "--end", "2026-08-05", "--max-workers", "2"],
        ),
        patch("stock_data.governance.audit.reconciliation.run_audit_range") as mock_run_range,
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
    from stock_data.governance.audit.reconciliation import run_index_audit

    index_df = pl.DataFrame(
        {
            "symbol": ["000001.SH", "399001.SZ"],
            "trade_date": ["2026-08-01", "2026-08-01"],
        }
    )

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch(
            "pathlib.Path.rglob",
            return_value=[
                Path(
                    "data/curated/tushare/market=CN/index_daily_bar/year=2026/month=08/data.parquet"
                )
            ],
        ),
        patch("polars.read_parquet", return_value=index_df),
    ):
        res = run_index_audit(date(2026, 8, 1), data_source="tushare")
        assert res["date"] == date(2026, 8, 1)
        assert res["actual_count"] == 2
        assert res["integrity_rate"] > 0


def test_run_index_audit_range():
    from stock_data.governance.audit.reconciliation import run_index_audit_range

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
            "stock_data.governance.audit.reconciliation.get_trading_calendar",
            return_value=[date(2026, 8, 1), date(2026, 8, 2)],
        ),
        patch("stock_data.governance.audit.reconciliation.run_index_audit", return_value=mock_res),
    ):
        res = run_index_audit_range(date(2026, 8, 1), date(2026, 8, 2), data_source="tushare")
        assert res["total_days"] == 2
        assert res["perfect_days"] == 2
        assert res["avg_integrity_rate"] == 100.0


def test_audit_main_index_cli():
    with (
        patch("sys.argv", ["audit", "--mode", "index", "--date", "2026-08-01"]),
        patch("stock_data.governance.audit.reconciliation.run_index_audit") as mock_run_index,
    ):
        audit_main()
        mock_run_index.assert_called_once_with(date(2026, 8, 1), data_source="tushare")


def test_run_daily_basic_audit():
    from stock_data.governance.audit.reconciliation import run_daily_basic_audit

    bar_df = pl.DataFrame(
        {"symbol": ["600000.SH", "000001.SZ"], "trade_date": ["2026-08-01", "2026-08-01"]}
    )
    db_df = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": ["2026-08-01"]})

    def mock_read(pattern):
        pattern_str = str(pattern)
        if "stock_daily_bar" in pattern_str:
            return bar_df
        return db_df

    def mock_glob(self, pattern):
        return [self / "data.parquet"]

    with (
        patch("pathlib.Path.glob", mock_glob),
        patch("pathlib.Path.exists", return_value=True),
        patch("polars.read_parquet", side_effect=mock_read),
    ):
        res = run_daily_basic_audit(date(2026, 8, 1))
        assert res["bar_count"] == 2
        assert res["basic_count"] == 1
        assert res["match_count"] == 1
        assert res["integrity_rate"] == 50.0


def test_run_adj_factor_audit():
    from stock_data.governance.audit.reconciliation import run_adj_factor_audit

    basic_df = pl.DataFrame(
        {"symbol": ["600000.SH", "000001.SZ"], "list_date": ["19991110", "19910403"]}
    )
    adj_df = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": ["2026-08-01"]})

    def mock_read(pattern):
        pattern_str = str(pattern)
        if "stock_basic" in pattern_str:
            return basic_df
        return adj_df

    def mock_glob(self, pattern):
        return [self / "data.parquet"]

    with (
        patch("pathlib.Path.glob", mock_glob),
        patch(
            "pathlib.Path.rglob",
            return_value=[
                Path("data/curated/tushare/market=CN/stock_basic/data.parquet"),
                Path("data/curated/tushare/market=CN/adj_factor/year=2026/month=08/data.parquet"),
            ],
        ),
        patch("pathlib.Path.exists", return_value=True),
        patch("polars.read_parquet", side_effect=mock_read),
    ):
        res = run_adj_factor_audit(date(2026, 8, 1))
        assert res["expected_count"] == 2
        assert res["actual_count"] == 1
        assert res["coverage_rate"] == 50.0


def test_raw_curated_reconciliation_detects_key_mismatch(tmp_path, monkeypatch):
    from stock_data.governance.audit.reconciliation import _run_raw_curated_reconciliation

    raw_root = tmp_path / "raw"
    curated_root = tmp_path / "curated"
    monkeypatch.setattr(
        "stock_data.governance.audit.reconciliation.data_settings.raw_data_dir", raw_root
    )
    monkeypatch.setattr(
        "stock_data.governance.audit.reconciliation.data_settings.curated_data_dir", curated_root
    )

    raw_path = raw_root / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    curated_path = (
        curated_root / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    )
    raw_path.mkdir(parents=True)
    curated_path.mkdir(parents=True)

    pl.DataFrame(
        {"ts_code": ["600000.SH", "000001.SZ"], "trade_date": ["20260801", "20260801"]}
    ).write_parquet(raw_path / "data.parquet")
    pl.DataFrame({"symbol": ["600000.SH"], "trade_date": ["2026-08-01"]}).write_parquet(
        curated_path / "data.parquet"
    )

    result = _run_raw_curated_reconciliation(date(2026, 8, 1), "tushare")

    assert result["raw_curated_status"] == "FAILED"
    assert result["raw_count"] == 2
    assert result["curated_count"] == 1
    assert result["missing_in_curated_count"] == 1


def test_raw_bar_reconciliation_reuses_units_and_listing_dates(monkeypatch):
    from stock_data.governance.audit.reconciliation import _clean_raw_bar_frame
    from stock_data.pipeline.cleaner.bar_cleaner import BarDataCleaner

    monkeypatch.setattr(
        BarDataCleaner,
        "load_listing_dates",
        staticmethod(
            lambda data_source: {
                "000001.SZ": date(2026, 8, 2),
                "000002.SZ": date(2020, 1, 1),
            }
        ),
    )
    raw = pl.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ"],
            "trade_date": ["20260801", "20260805"],
            "open": [10.0, 20.0],
            "high": [10.5, 20.5],
            "low": [9.5, 19.5],
            "close": [10.0, 20.0],
            "vol": [100.0, 100.0],
            "amount": [100.0, 200000.0],
            "source_unit_note": [
                "native unit: thousand yuan",
                "amount is normalized to yuan",
            ],
        }
    )

    cleaned, filtered_count = _clean_raw_bar_frame("stock_daily_bar", "tushare", raw)

    assert filtered_count == 1
    assert cleaned["ts_code"].to_list() == ["000002.SZ"]
    assert cleaned["volume"].to_list() == [10000.0]
    assert cleaned["amount"].to_list() == [200000.0]


def test_raw_lixinger_index_fundamental_filters_empty_holiday_rows() -> None:
    from stock_data.governance.audit.reconciliation import _clean_raw_frame

    raw = pl.DataFrame(
        {
            "stockCode": ["000300", "000905", "000852"],
            "date": ["2022-04-05", "2026-08-14", "2026-08-14"],
            "pe_ttm.ew": [None, 12.0, None],
            "pe_ttm.mcw": [None, 11.0, None],
            "pb.ew": [None, 1.5, None],
            "pb.mcw": [None, 1.4, 1.3],
            "ps_ttm.ew": [None, 1.2, None],
            "ps_ttm.mcw": [None, 1.1, None],
            "dyr.ew": [None, 0.03, None],
            "dyr.mcw": [None, 0.028, None],
            "mc": [None, 100.0, None],
        }
    )

    cleaned, filtered_count = _clean_raw_frame("index_fundamental", "lixinger", raw)

    assert filtered_count == 1
    assert cleaned["stockCode"].to_list() == ["000905", "000852"]


def test_raw_curated_reconciliation_exempts_lixinger_curated_only_dataset() -> None:
    from stock_data.governance.audit.reconciliation import _run_raw_curated_reconciliation

    result = _run_raw_curated_reconciliation(date(2026, 8, 14), "lixinger", "sw_2021_fundamental")

    assert result["raw_curated_status"] == "SKIPPED"
    assert result["raw_curated_exempt"] is True
    assert "403" in result["raw_curated_reason"]


def test_raw_curated_reconciliation_uses_lixinger_composite_primary_key(
    tmp_path, monkeypatch
) -> None:
    from stock_data.governance.audit.reconciliation import _run_raw_curated_reconciliation

    raw_root = tmp_path / "raw"
    curated_root = tmp_path / "curated"
    monkeypatch.setattr(
        "stock_data.governance.audit.reconciliation.data_settings.raw_data_dir", raw_root
    )
    monkeypatch.setattr(
        "stock_data.governance.audit.reconciliation.data_settings.curated_data_dir", curated_root
    )

    raw_dir = raw_root / "lixinger" / "market=CN" / "sw_2021_constituents"
    curated_dir = curated_root / "lixinger" / "market=CN" / "sw_2021_constituents"
    raw_dir.mkdir(parents=True)
    curated_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "industryCode": ["110000", "110000", "220000"],
            "stockCode": ["600519", "000001", "600519"],
        }
    ).write_parquet(raw_dir / "data.parquet")
    pl.DataFrame(
        {
            "industryCode": ["110000", "110000", "220000"],
            "symbol": ["600519", "000001", "600519"],
        }
    ).write_parquet(curated_dir / "data.parquet")

    result = _run_raw_curated_reconciliation(date(2026, 8, 14), "lixinger", "sw_2021_constituents")

    assert result["raw_curated_status"] == "PASSED"
    assert result["raw_key_count"] == 3
    assert result["curated_key_count"] == 3
    assert result["missing_in_curated_count"] == 0
    assert result["extra_in_curated_count"] == 0


def test_run_hk_hold_audit():
    from stock_data.governance.audit.reconciliation import run_hk_hold_audit

    hk_df = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": ["2026-08-01"], "vol": [100000.0]})

    def mock_glob(self, pattern):
        return [self / "data.parquet"]

    with (
        patch("pathlib.Path.glob", mock_glob),
        patch("pathlib.Path.exists", return_value=True),
        patch("polars.read_parquet", return_value=hk_df),
    ):
        res = run_hk_hold_audit(date(2026, 8, 1))
        assert res["symbols_count"] == 1
        assert res["total_vol"] == 100000.0


def test_run_sw_industry_audit():
    from stock_data.governance.audit import run_sw_industry_audit

    const_df = pl.DataFrame({"symbol": ["110000", "210000"]})
    fund_df = pl.DataFrame({"symbol": ["110000"], "trade_date": ["2026-08-01"]})

    def mock_read(pattern: object) -> pl.DataFrame:
        pattern_str = str(pattern)
        if "sw_2021_constituents" in pattern_str:
            return const_df
        return fund_df

    with (
        patch(
            "pathlib.Path.rglob",
            return_value=[
                Path("data/curated/lixinger/market=CN/sw_2021_constituents/data.parquet"),
                Path("data/curated/lixinger/market=CN/sw_2021_fundamental/data.parquet"),
            ],
        ),
        patch("polars.read_parquet", side_effect=mock_read),
    ):
        res = run_sw_industry_audit(date(2026, 8, 1))
        assert res["constituents_industry_count"] == 2
        assert res["actual_industry_count"] == 1


def test_run_sw_daily_audit():
    from stock_data.governance.audit import run_sw_daily_audit

    sw_df = pl.DataFrame(
        {"symbol": ["801010.SI", "801030.SI"], "trade_date": ["2026-08-01", "2026-08-01"]}
    )

    with patch("polars.read_parquet", return_value=sw_df):
        res = run_sw_daily_audit(date(2026, 8, 1))
        assert res["expected_count"] == 31
        assert res["actual_count"] == 2
        assert res["actual_symbols"] == ["801010.SI", "801030.SI"]


def test_filter_target_date_formats():
    from datetime import datetime

    from stock_data.governance.audit.reconciliation import _filter_target_date

    target = date(2026, 8, 1)

    # 1. Date 类型
    df_date = pl.DataFrame({"trade_date": [date(2026, 8, 1), date(2026, 8, 2)]})
    assert len(_filter_target_date(df_date, target)) == 1

    # 2. Datetime 类型
    df_dt = pl.DataFrame({"trade_date": [datetime(2026, 8, 1, 15, 0), datetime(2026, 8, 2, 9, 30)]})
    assert len(_filter_target_date(df_dt, target)) == 1

    # 3. 包含时间戳的字符串
    df_str_ts = pl.DataFrame({"trade_date": ["2026-08-01 00:00:00", "2026-08-02 00:00:00"]})
    assert len(_filter_target_date(df_str_ts, target)) == 1

    # 4. 紧凑型字符串与带斜杠字符串
    df_mixed = pl.DataFrame({"trade_date": ["20260801", "2026/08/01", "20260802"]})
    assert len(_filter_target_date(df_mixed, target)) == 2


def test_extract_identity_keys_formats():
    from stock_data.governance.audit.reconciliation import _extract_identity_keys_frame

    # 测试 ts_code 优先及 Date/Datetime/String 日期格式转换
    df = pl.DataFrame(
        {
            "ts_code": ["000001.SZ", "600000.SH"],
            "symbol": ["ADJ_FACTOR", "ADJ_FACTOR"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 2)],
        }
    )
    keys_df = _extract_identity_keys_frame(df)
    assert len(keys_df) == 2
    assert "000001.SZ" in keys_df["symbol"].to_list()
    assert "600000.SH" in keys_df["symbol"].to_list()
    assert "20260801" in keys_df["trade_date"].to_list()
