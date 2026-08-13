"""RAW 原始数据存储引擎单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock.data.storage.raw_store import RawDataStorage


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
