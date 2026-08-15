"""RAW 原始数据存储引擎单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock.data.storage.raw_store import RawDataStorage


class TrackingLock:
    def __init__(self) -> None:
        self.entered = 0

    def __enter__(self) -> "TrackingLock":
        self.entered += 1
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


def test_raw_storage_save_and_load(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    target_date = date(2026, 8, 12)

    dummy_df = pl.DataFrame(
        {
            "ts_code": ["600000.SH"],
            "trade_date": ["20260812"],
            "close": [10.5],
        }
    )

    # 1. 验证写入
    saved_path = store.save_raw("tushare", "daily", target_date, dummy_df)
    assert saved_path.exists()
    assert "year=2026" in str(saved_path)
    assert "month=08" in str(saved_path)

    # 2. 验证 has_raw
    assert store.has_raw("tushare", "daily", target_date)

    # 3. 验证读取
    loaded_df = store.load_raw("tushare", "daily", target_date)
    assert loaded_df is not None
    assert len(loaded_df) == 1
    assert loaded_df["ts_code"][0] == "600000.SH"


def test_raw_storage_missing_cache(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    missing_date = date(2020, 1, 1)

    assert not store.has_raw("tushare", "daily", missing_date)
    assert store.load_raw("tushare", "daily", missing_date) is None


def test_raw_storage_uses_endpoint_market_for_dataset_cache(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    target_date = date(2026, 8, 12)
    cache_path = (
        tmp_path
        / "yfinance"
        / "market=US"
        / "stock_daily_bar"
        / "year=2026"
        / "month=08"
        / "data.parquet"
    )
    cache_path.parent.mkdir(parents=True)
    pl.DataFrame({"symbol": ["AAPL"], "trade_date": ["20260812"]}).write_parquet(cache_path)

    assert store.has_raw("yfinance", "history", target_date)


def test_raw_storage_has_raw_requires_target_date_in_month_file(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    cache_path = (
        tmp_path
        / "yfinance"
        / "market=US"
        / "stock_daily_bar"
        / "year=2026"
        / "month=08"
        / "data.parquet"
    )
    cache_path.parent.mkdir(parents=True)
    pl.DataFrame({"symbol": ["AAPL"], "trade_date": ["20260811"]}).write_parquet(cache_path)

    assert not store.has_raw("yfinance", "history", date(2026, 8, 12))


def test_raw_storage_save_dataset_multi_month(tmp_path: Path) -> None:
    from stock.core.contracts import DatasetKey

    store = RawDataStorage(base_dir=tmp_path)
    df_multi = pl.DataFrame(
        {
            "ts_code": ["000300.SH", "000300.SH"],
            "trade_date": ["20140801.0", "20260812"],
            "pe": [10.5, 12.3],
        }
    )
    key = DatasetKey(
        provider="tushare",
        dataset="index_dailybasic",
        endpoint="index_dailybasic",
        start_date=date(2014, 8, 1),
        end_date=date(2026, 8, 12),
    )
    store.save_dataset(key, df_multi)

    p_2014 = (
        tmp_path
        / "tushare"
        / "market=CN"
        / "index_dailybasic"
        / "year=2014"
        / "month=08"
        / "data.parquet"
    )
    p_2026 = (
        tmp_path
        / "tushare"
        / "market=CN"
        / "index_dailybasic"
        / "year=2026"
        / "month=08"
        / "data.parquet"
    )

    assert p_2014.exists()
    assert p_2026.exists()
    df_14 = pl.read_parquet(p_2014)
    df_26 = pl.read_parquet(p_2026)
    assert len(df_14) == 1
    assert len(df_26) == 1
    assert df_14["trade_date"][0] == "20140801.0"
    assert df_26["trade_date"][0] == "20260812"


def test_raw_storage_batch_buffer_append_uses_file_lock(tmp_path: Path) -> None:
    from stock.core.contracts import DatasetKey

    store = RawDataStorage(base_dir=tmp_path)
    lock = TrackingLock()
    store._file_lock = lock
    store.enable_batch_mode()
    key = DatasetKey(
        provider="tushare",
        dataset="daily_basic",
        endpoint="daily_basic",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 10),
    )
    df = pl.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260810"],
            "close": [10.0],
        }
    )

    saved_path = store.save_dataset(key, df)

    assert lock.entered == 1
    assert saved_path in store._write_buffer
    assert len(store._write_buffer[saved_path]) == 1
