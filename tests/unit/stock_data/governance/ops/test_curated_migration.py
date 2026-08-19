from datetime import date
from pathlib import Path

import polars as pl
import pytest
from scripts.migrate_curated_schema_v2 import migrate_curated


def _legacy_bar_path(tmp_path: Path) -> Path:
    path = tmp_path / "curated/tushare/market=CN/stock_daily_bar/year=2026/month=08/data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "date": ["2026-08-14"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "amount": [10500.0],
        }
    ).write_parquet(path)
    return path


def test_curated_migration_dry_run_does_not_write(tmp_path: Path) -> None:
    path = _legacy_bar_path(tmp_path)

    result = migrate_curated(tmp_path / "curated")

    assert result["files_scanned"] == 1
    assert result["files_changed"] == 1
    assert result["applied"] is False
    assert not path.with_name("data.bak.parquet").exists()
    assert set(pl.read_parquet(path).columns) == {
        "ts_code",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    }


def test_curated_migration_apply_writes_backup_and_v2_schema(tmp_path: Path) -> None:
    path = _legacy_bar_path(tmp_path)

    result = migrate_curated(tmp_path / "curated", apply=True)
    migrated = pl.read_parquet(path)

    assert result["applied"] is True
    assert path.with_name("data.bak.parquet").exists()
    assert migrated["symbol"].to_list() == ["000001.SZ"]
    assert migrated["trade_date"].to_list() == [date(2026, 8, 14)]
    assert migrated["schema_version"].to_list() == ["v2"]
    assert migrated["data_source"].to_list() == ["tushare"]
    assert migrated.schema["updated_at"] == pl.Datetime("us", "UTC")


def test_curated_migration_normalizes_index_valuation_legacy_field(tmp_path: Path) -> None:
    path = tmp_path / "curated/yfinance/market=US/index_valuation/data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["SPY"],
            "trade_date": [date(2026, 8, 14)],
            "trailing_pe": [20.0],
            "forward_pe": [19.0],
            "price_to_book": [2.0],
            "price_to_sales": [3.0],
            "dividend_yield": [1.2],
            "market_cap": [None],
            "total_assets": [500.0],
            "data_source": ["yfinance"],
            "target_index": ["^GSPC"],
            "market": ["US"],
            "schema_version": ["v2"],
        }
    ).write_parquet(path)

    migrate_curated(tmp_path / "curated", apply=True)
    migrated = pl.read_parquet(path)

    assert migrated["market_cap"].to_list() == [500.0]
    assert "total_assets" not in migrated.columns


def test_curated_migration_fills_etf_history_schema_without_dropping_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "curated/tushare/market=CN/etf_share_size/year=2012/month=01/data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "trade_date": ["2012-01-04"],
            "symbol": ["510300.SH"],
            "total_share": [100.0],
            "total_size": ["250.0"],
        }
    ).write_parquet(path)

    migrate_curated(tmp_path / "curated", apply=True)
    migrated = pl.read_parquet(path)

    assert migrated.schema["trade_date"] == pl.Date
    assert migrated.schema["total_size"] == pl.Float64
    assert migrated["total_share"].to_list() == [100.0]
    assert migrated["total_size"].to_list() == [250.0]
    assert migrated.schema["float_size"] == pl.Float64
    assert migrated["float_size"].to_list() == [None]


def test_curated_migration_maps_express_legacy_alias_and_fills_update_flag(
    tmp_path: Path,
) -> None:
    path = tmp_path / "curated/tushare/market=CN/express/year=2021/month=12/data.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "ann_date": ["20220301"],
            "end_date": ["20211231"],
            "diluted_roe": ["8.5"],
            "yoy_net_profit": ["123.0"],
        }
    ).write_parquet(path)

    migrate_curated(tmp_path / "curated", apply=True)
    migrated = pl.read_parquet(path)

    assert migrated.schema["ann_date"] == pl.Date
    assert migrated.schema["end_date"] == pl.Date
    assert migrated.schema["diluted_roe"] == pl.Float64
    assert migrated["prior_period_net_profit"].to_list() == [123.0]
    assert "yoy_net_profit" not in migrated.columns
    assert migrated["update_flag"].to_list() == [None]


def test_curated_migration_rejects_non_curated_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="curated"):
        migrate_curated(tmp_path)
