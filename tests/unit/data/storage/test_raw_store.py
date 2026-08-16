"""RAW 原始数据存储引擎单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock.core.contracts import DatasetKey, instrument_for_symbol
from stock.data.storage.raw_store import RawDataStorage
from stock.exceptions import DataValidationError


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


def test_raw_storage_legacy_has_raw_checks_symbol(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    target_date = date(2026, 8, 12)
    dummy_df = pl.DataFrame(
        {
            "ts_code": ["600000.SH"],
            "trade_date": ["20260812"],
            "close": [10.5],
        }
    )
    store.save_raw("tushare", "daily", target_date, dummy_df)

    assert store.has_raw("tushare", "daily", target_date, symbol="600000.SH")
    assert not store.has_raw("tushare", "daily", target_date, symbol="000001.SZ")


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


def test_raw_storage_has_raw_requires_symbol_date_intersection(tmp_path: Path) -> None:
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
    pl.DataFrame(
        {
            "symbol": ["AAPL", "MSFT"],
            "trade_date": ["20260803", "20260804"],
        }
    ).write_parquet(cache_path)

    assert not store.has_raw("yfinance", "history", date(2026, 8, 4), symbol="AAPL")
    assert not store.has_raw("yfinance", "history", date(2026, 8, 3), symbol="MSFT")
    assert store.has_raw("yfinance", "history", date(2026, 8, 4), symbol="MSFT")


def test_raw_storage_load_dataset_requires_symbol_date_intersection(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    saved_key = DatasetKey(
        provider="yfinance",
        dataset="stock_daily_bar",
        endpoint="history",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
    )
    store.save_dataset(
        saved_key,
        pl.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "trade_date": ["20260801", "20260802"],
                "close": [100.0, 200.0],
            }
        ),
    )
    requested_key = DatasetKey(
        provider="yfinance",
        dataset="stock_daily_bar",
        endpoint="history",
        start_date=date(2026, 8, 2),
        end_date=date(2026, 8, 2),
        instrument=instrument_for_symbol("AAPL", "yfinance"),
    )

    assert store.load_dataset(requested_key) is None


def test_raw_storage_save_dataset_multi_month(tmp_path: Path) -> None:
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


def test_raw_storage_rejects_mixed_invalid_dates_without_partial_write(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    key = DatasetKey(
        provider="tushare",
        dataset="daily_basic",
        endpoint="daily_basic",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
    )
    frame = pl.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ"],
            "trade_date": ["20260801", "20261302"],
            "close": [10.0, 20.0],
        }
    )

    with pytest.raises(DataValidationError, match="无法解析的日期"):
        store.save_dataset(key, frame)

    assert not list(tmp_path.rglob("*.parquet"))


def test_raw_storage_load_dataset_spans_month_partitions(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    key = DatasetKey(
        provider="tushare",
        dataset="daily_basic",
        endpoint="daily_basic",
        start_date=date(2026, 1, 30),
        end_date=date(2026, 2, 2),
    )
    store.save_dataset(
        key,
        pl.DataFrame(
            {
                "ts_code": ["000001.SZ", "000001.SZ"],
                "trade_date": ["20260130", "20260202"],
                "close": [10.0, 10.2],
            }
        ),
    )

    loaded = store.load_dataset(key)

    assert loaded is not None
    assert loaded.sort("trade_date")["trade_date"].to_list() == ["20260130", "20260202"]


def test_raw_storage_load_dataset_misses_when_month_partition_missing(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    saved_key = DatasetKey(
        provider="tushare",
        dataset="daily_basic",
        endpoint="daily_basic",
        start_date=date(2026, 1, 30),
        end_date=date(2026, 1, 30),
    )
    store.save_dataset(
        saved_key,
        pl.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260130"], "close": [10.0]}),
    )
    requested_key = DatasetKey(
        provider="tushare",
        dataset="daily_basic",
        endpoint="daily_basic",
        start_date=date(2026, 1, 30),
        end_date=date(2026, 2, 2),
    )

    assert store.load_dataset(requested_key) is None


def test_raw_storage_preserves_source_fields_without_curated_metadata(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    key = DatasetKey(
        provider="tushare",
        dataset="daily_basic",
        endpoint="daily_basic",
        start_date=date(2026, 8, 12),
        end_date=date(2026, 8, 12),
    )
    raw_df = pl.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260812"],
            "vol": [123.45],
            "amount": [678.9],
            "vendor_extra": ["source-specific"],
        }
    )

    store.save_dataset(key, raw_df)
    loaded = store.load_dataset(key)

    assert loaded is not None
    assert loaded.columns == raw_df.columns
    assert loaded.to_dict(as_series=False) == raw_df.to_dict(as_series=False)
    assert not {
        "data_source",
        "source_endpoint",
        "request_id",
        "updated_at",
        "market",
        "exchange",
        "currency",
        "adjustment",
        "schema_version",
    }.intersection(loaded.columns)


def test_raw_storage_margin_deduplicates_mixed_date_formats(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    key = DatasetKey(
        provider="tushare",
        dataset="margin",
        endpoint="margin",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
    )
    raw_df = pl.DataFrame(
        {
            "trade_date": ["20240102", "2024-01-02", "20240102"],
            "exchange_id": ["SSE", "SSE", "SZSE"],
            "rzye": [100.0, 100.0, 200.0],
        }
    )

    store.save_dataset(key, raw_df)
    loaded = pl.read_parquet(tmp_path / "tushare" / "market=CN" / "margin" / "data.parquet")
    normalized = loaded.with_columns(
        pl.col("trade_date")
        .cast(pl.Utf8, strict=False)
        .str.replace_all("-", "")
        .alias("_trade_date")
    )

    assert len(loaded) == 2
    assert normalized.group_by(["_trade_date", "exchange_id"]).len().filter(
        pl.col("len") > 1
    ).is_empty()
    assert "symbol" not in loaded.columns


def test_raw_storage_margin_cache_requires_trade_date_exchange_coverage(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    target_date = date(2026, 8, 14)
    key = DatasetKey(
        provider="tushare",
        dataset="margin",
        endpoint="margin",
        start_date=target_date,
        end_date=target_date,
    )
    partial = pl.DataFrame(
        {
            "trade_date": ["20260814"],
            "exchange_id": ["SSE"],
            "rzye": [100.0],
        }
    )
    complete = pl.DataFrame(
        {
            "trade_date": ["20260814", "20260814", "20260814"],
            "exchange_id": ["SSE", "SZSE", "BSE"],
            "rzye": [100.0, 200.0, 3.0],
        }
    )

    store.save_dataset(key, partial)
    assert store.load_dataset(key) is None
    assert not store.has_raw("tushare", "margin", target_date)
    assert (tmp_path / "tushare/market=CN/margin/data.parquet").exists()

    store.save_dataset(key, complete)
    loaded = store.load_dataset(key)
    assert loaded is not None
    assert set(loaded["exchange_id"].to_list()) == {"SSE", "SZSE", "BSE"}
    assert store.has_raw("tushare", "margin", target_date)


def test_raw_storage_margin_cache_uses_exchange_start_dates(tmp_path: Path) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    target_date = date(2022, 8, 12)
    key = DatasetKey(
        provider="tushare",
        dataset="margin",
        endpoint="margin",
        start_date=target_date,
        end_date=target_date,
    )
    store.save_dataset(
        key,
        pl.DataFrame(
            {
                "trade_date": ["20220812", "20220812"],
                "exchange_id": ["SSE", "SZSE"],
                "rzye": [100.0, 200.0],
            }
        ),
    )

    assert store.load_dataset(key) is not None
    assert store.has_raw("tushare", "margin", target_date)


def test_raw_storage_replaces_incompatible_cache_with_recoverable_backup(
    tmp_path: Path,
) -> None:
    store = RawDataStorage(base_dir=tmp_path)
    key = DatasetKey(
        provider="lixinger",
        dataset="sw_2021_constituents",
        endpoint="sw_2021_constituents",
        start_date=date(2026, 8, 15),
        end_date=date(2026, 8, 15),
    )
    legacy = pl.DataFrame({"symbol": ["110000"], "constituents": [[]]})
    fresh = pl.DataFrame(
        {"industryCode": ["110000"], "stockCode": ["600519"], "market": ["CN"]}
    )

    store.save_dataset(key, legacy)
    store.save_dataset(key, fresh, replace_existing=True)

    active = tmp_path / "lixinger" / "market=CN" / "sw_2021_constituents" / "data.parquet"
    backup = (
        tmp_path
        / "lixinger"
        / "market=CN"
        / "sw_2021_constituents"
        / "data.legacy.bak.parquet"
    )
    assert pl.read_parquet(active).columns == fresh.columns
    assert pl.read_parquet(backup).columns == legacy.columns


def test_raw_storage_batch_buffer_append_uses_file_lock(tmp_path: Path) -> None:
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


def test_raw_storage_sw_daily_legacy_index_id_multi_industry_preserved(tmp_path: Path) -> None:
    """验证使用 legacy index_id 列名时，多行业依次写入同一分区不会被单行业覆盖。"""
    from stock.core.contracts import DatasetKey

    store = RawDataStorage(base_dir=tmp_path)
    target_date = date(2026, 8, 3)

    # 模拟依次写入 31 个申万一级行业
    for i in range(1, 32):
        ind_code = f"8010{i:02d}.SI"
        key = DatasetKey(
            provider="tushare",
            dataset="sw_daily",
            endpoint="sw_daily",
            start_date=target_date,
            end_date=target_date,
        )
        df_ind = pl.DataFrame(
            {
                "trade_date": ["20260803"],
                "index_id": [ind_code],
                "index_name": [f"行业_{i}"],
                "close": [float(i * 10)],
            }
        )
        store.save_dataset(key, df_ind)

    # 验证最终落盘的 RAW 文件包含全部 31 个行业
    raw_file = (
        tmp_path / "tushare" / "market=CN" / "sw_daily" / "year=2026" / "month=08" / "data.parquet"
    )
    assert raw_file.exists()
    df_loaded = pl.read_parquet(raw_file)
    assert len(df_loaded) == 31
    assert df_loaded["index_id"].n_unique() == 31


def test_raw_storage_constituents_preserves_stock_across_industries(tmp_path: Path) -> None:
    """成分股 RAW 必须按行业代码和股票代码联合去重。"""
    store = RawDataStorage(base_dir=tmp_path)
    target_date = date(2026, 8, 14)
    key = DatasetKey(
        provider="lixinger",
        dataset="sw_2021_constituents",
        endpoint="sw_2021_constituents",
        start_date=target_date,
        end_date=target_date,
    )

    store.save_dataset(
        key,
        pl.DataFrame(
            {
                "industryCode": ["110000", "220000", "110000"],
                "stockCode": ["600519", "600519", "600519"],
                "market": ["a", "a", "a"],
            }
        ),
    )

    loaded = pl.read_parquet(
        tmp_path / "lixinger" / "market=CN" / "sw_2021_constituents" / "data.parquet"
    )
    assert len(loaded) == 2
    assert set(zip(loaded["industryCode"], loaded["stockCode"], strict=True)) == {
        ("110000", "600519"),
        ("220000", "600519"),
    }


def test_raw_storage_heterogeneous_schema_coalesced_dedup(tmp_path: Path) -> None:
    """验证异构 Schema 对角线合并时不会发生空值键折叠，且支持幂等更新。"""
    from stock.core.contracts import DatasetKey

    store = RawDataStorage(base_dir=tmp_path)
    d = date(2026, 8, 7)
    key = DatasetKey(
        provider="tushare",
        dataset="sw_daily",
        endpoint="sw_daily",
        start_date=d,
        end_date=d,
    )

    # 批次 1: 存量 legacy 格式 (含 index_id)
    df_legacy = pl.DataFrame(
        {
            "trade_date": ["20260807", "20260807"],
            "index_id": ["801010.SI", "801020.SI"],
            "close": [100.0, 200.0],
        }
    )
    store.save_dataset(key, df_legacy)

    # 批次 2: 新接口格式 (含 ts_code，且包含 801010.SI 更新与 850001.SI 新增)
    df_new = pl.DataFrame(
        {
            "trade_date": ["20260807", "20260807"],
            "ts_code": ["801010.SI", "850001.SI"],
            "close": [105.0, 300.0],
        }
    )
    store.save_dataset(key, df_new)

    raw_file = (
        tmp_path / "tushare" / "market=CN" / "sw_daily" / "year=2026" / "month=08" / "data.parquet"
    )
    df_loaded = pl.read_parquet(raw_file)

    # 应该包含 3 个行业 (801010, 801020, 850001)，其中 801010 更新为 105.0
    assert len(df_loaded) == 3
    row_801010 = df_loaded.filter(
        (pl.col("ts_code") == "801010.SI") | (pl.col("index_id") == "801010.SI")
    )
    assert len(row_801010) == 1
    assert row_801010["close"][0] == 105.0
