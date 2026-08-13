"""StorageCompat 单元测试。"""

from datetime import datetime, timezone
from pathlib import Path
import polars as pl

from stock.data.storage.compat import StorageCompat


def test_is_artifact_path() -> None:
    assert StorageCompat.is_artifact_path(Path("data.bak.parquet")) is True
    assert StorageCompat.is_artifact_path(Path("data.tmp.parquet")) is True
    assert StorageCompat.is_artifact_path(Path("data.migration.tmp.parquet")) is True
    assert StorageCompat.is_artifact_path(Path("data.parquet")) is False


def test_canonical_dataset_name() -> None:
    assert StorageCompat.canonical_dataset_name("daily") == "stock_daily_bar"
    assert StorageCompat.canonical_dataset_name("daily_bar") == "stock_daily_bar"
    assert StorageCompat.canonical_dataset_name("history") == "stock_daily_bar"
    assert StorageCompat.canonical_dataset_name("daily_basic", "tushare") == "daily_basic"


def test_normalize_identity_columns() -> None:
    df = pl.DataFrame({"ts_code": ["000001.SZ"], "date": ["2026-08-10"], "close": [10.0]})
    normalized = StorageCompat.normalize_identity_columns(df)
    assert "symbol" in normalized.columns
    assert "trade_date" in normalized.columns
    assert "ts_code" not in normalized.columns
    assert "date" not in normalized.columns
    assert normalized["symbol"][0] == "000001.SZ"
    assert normalized["trade_date"][0] == "2026-08-10"


def test_normalize_datetime_columns() -> None:
    now_naive = datetime(2026, 8, 10, 12, 0, 0)
    df = pl.DataFrame({"updated_at": [now_naive]})
    normalized = StorageCompat.normalize_datetime_columns(df)
    assert normalized.schema["updated_at"] == pl.Datetime("us", "UTC")
