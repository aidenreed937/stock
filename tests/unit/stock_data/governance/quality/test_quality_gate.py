"""QualityGate 单元测试。"""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from stock_core.exceptions import DataValidationError
from stock_data.governance.quality.gate import QualityGate, run_quality_gate


def test_quality_gate_on_valid_data(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    valid_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": [date(2026, 8, 1)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [1000.0],
            "amount": [10500.0],
            "data_source": ["tushare"],
            "source_endpoint": ["stock_daily_bar"],
            "market": ["CN"],
            "exchange": ["SZSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v2"],
            "updated_at": [now_utc],
        }
    )
    valid_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    results = gate.validate_all()
    assert all(results.values())
    assert run_quality_gate(tmp_path)


def test_quality_gate_fails_on_unit_mismatch(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    bad_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 12,
            "trade_date": [date(2026, 8, 1)] * 12,
            "open": [10.0] * 12,
            "high": [11.0] * 12,
            "low": [9.5] * 12,
            "close": [10.5] * 12,
            "volume": [10.0] * 12,
            "amount": [10500.0] * 12,
            "data_source": ["tushare"] * 12,
            "source_endpoint": ["stock_daily_bar"] * 12,
            "market": ["CN"] * 12,
            "exchange": ["SZSE"] * 12,
            "currency": ["CNY"] * 12,
            "adjustment": ["raw"] * 12,
            "schema_version": ["v2"] * 12,
            "updated_at": [now_utc] * 12,
        }
    )
    bad_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_stock_daily_bar_units(gate._active_parquet_files())
    assert not run_quality_gate(tmp_path)


def test_quality_gate_fails_on_index_bar_missing_ohlc(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "index_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    bad_df = pl.DataFrame(
        {
            "symbol": ["000300.SH"],
            "trade_date": [date(2026, 8, 1)],
            "open": [4000.0],
            "close": [4010.0],
            "volume": [1000.0],
            "amount": [4010000.0],
            "data_source": ["tushare"],
            "source_endpoint": ["index_daily_bar"],
            "market": ["CN"],
            "exchange": ["SSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v2"],
            "updated_at": [now_utc],
        }
    )
    bad_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_schema_contracts(gate._active_parquet_files())


def test_quality_gate_checks_adjustment_for_fund_daily(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "fund_daily" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    mixed_df = pl.DataFrame(
        {
            "symbol": ["510300.SH", "510500.SH"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "open": [4.0, 5.0],
            "high": [4.1, 5.1],
            "low": [3.9, 4.9],
            "close": [4.05, 5.05],
            "volume": [1000.0, 1000.0],
            "amount": [4050.0, 5050.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["fund_daily", "fund_daily"],
            "market": ["CN", "CN"],
            "exchange": ["SSE", "SSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "hfq"],
            "schema_version": ["v2", "v2"],
            "updated_at": [now_utc, now_utc],
        }
    )
    mixed_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_no_mixed_adjustment(gate._active_parquet_files())


def test_quality_gate_fails_on_duplicate_keys(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    dup_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.5, 9.5],
            "close": [10.5, 10.5],
            "volume": [1000.0, 1000.0],
            "amount": [10500.0, 10500.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["stock_daily_bar", "stock_daily_bar"],
            "market": ["CN", "CN"],
            "exchange": ["SZSE", "SZSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "raw"],
            "schema_version": ["v2", "v2"],
            "updated_at": [now_utc, now_utc],
        }
    )
    dup_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_no_duplicate_keys(gate._active_parquet_files())
    with pytest.raises(DataValidationError, match="质量门禁检测失败"):
        gate.validate_all()


def test_quality_gate_uses_registered_event_keys(tmp_path: Path) -> None:
    target_dir = tmp_path / "tushare" / "market=CN" / "cn_schedule"
    target_dir.mkdir(parents=True, exist_ok=True)
    valid_df = pl.DataFrame(
        {
            "market": ["CN", "CN"],
            "month": ["202611", "202611"],
            "publish_date": ["20261109", "20261116"],
            "title": ["居民消费价格指数月度报告", "商品住宅销售价格指数月度报告"],
        }
    )
    path = target_dir / "data.parquet"
    valid_df.write_parquet(path)

    gate = QualityGate(tmp_path)
    assert gate.assert_no_duplicate_keys(gate._active_parquet_files())

    pl.concat([valid_df, valid_df.head(1)]).write_parquet(path)
    assert not gate.assert_no_duplicate_keys(gate._active_parquet_files())


def test_quality_gate_fails_on_mixed_adjustment(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    mixed_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.5, 9.5],
            "close": [10.5, 10.5],
            "volume": [1000.0, 1000.0],
            "amount": [10500.0, 10500.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["stock_daily_bar", "stock_daily_bar"],
            "market": ["CN", "CN"],
            "exchange": ["SZSE", "SZSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "hfq"],  # 混合复权
            "schema_version": ["v2", "v2"],
            "updated_at": [now_utc, now_utc],
        }
    )
    mixed_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_no_mixed_adjustment(gate._active_parquet_files())
