"""ETL 清洗、标准化与 Pipeline 数据流单元测试。"""

from datetime import date

import polars as pl

from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.fetcher.example import MockDataFetcher
from stock.data.normalizer.bar_normalizer import BarDataNormalizer
from stock.data.pipeline import MarketDataPipeline
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.data.storage.raw_store import RawDataStorage


def test_bar_cleaner_filtering() -> None:
    cleaner = BarDataCleaner()
    # 构造包含脏数据的数据帧 (零价格、最高价低于开盘价、包含 null)
    raw_df = pl.DataFrame(
        {
            "symbol": ["TEST", "TEST", "TEST", "TEST"],
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)],
            "open": [10.0, -1.0, 10.0, None],
            "high": [12.0, 12.0, 9.0, 12.0],  # 9.0 低于 open 10.0 -> 非法物理数据
            "low": [9.0, 8.0, 8.0, 9.0],
            "close": [11.0, 11.0, 9.5, 11.0],
            "volume": [1000.0, 1000.0, 1000.0, 1000.0],
            "amount": [11000.0, 11000.0, 9500.0, 11000.0],
        }
    )

    cleaned_df = cleaner.clean(raw_df)
    # 只有第一条 (2026-01-01) 是完全合规数据
    assert len(cleaned_df) == 1
    assert cleaned_df["trade_date"][0] == date(2026, 1, 1)


def test_bar_normalizer_renaming() -> None:
    normalizer = BarDataNormalizer()
    # 构造含异构列名 (ts_code, vol, date 为 string) 的数据帧
    raw_df = pl.DataFrame(
        {
            "ts_code": ["600000.SH"],
            "date": ["2026-01-01"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "vol": [5000.0],
            "amount": [52500.0],
        }
    )

    normalized_df = normalizer.normalize(raw_df)
    assert "symbol" in normalized_df.columns
    assert "trade_date" in normalized_df.columns
    assert "volume" in normalized_df.columns
    assert normalized_df["trade_date"].dtype == pl.Date


def test_market_data_pipeline(tmp_path) -> None:
    fetcher = MockDataFetcher()
    store = DuckDBMarketStore(storage_dir=tmp_path / "curated")
    raw_store = RawDataStorage(base_dir=tmp_path / "raw")
    pipeline = MarketDataPipeline(
        fetcher=fetcher, store=store, raw_store=raw_store, data_source="tushare"
    )

    # 首次拉取并入库
    df = pipeline.sync_daily_bars("TEST.SH", date(2026, 1, 1), date(2026, 1, 10))
    assert not df.is_empty()
    assert "symbol" in df.columns
    assert "data_source" in df.columns
    assert "updated_at" in df.columns
    assert df["data_source"][0] == "tushare"

    # 验证 RAW 缓存落盘
    assert raw_store.has_raw("tushare", "daily", date(2026, 1, 10))

    # 第二次读取时应直接命中 RAW 缓存
    cached_df = pipeline.sync_daily_bars(
        "TEST.SH", date(2026, 1, 1), date(2026, 1, 10), use_raw_cache=True
    )
    assert len(cached_df) == len(df)

    # 验证在 DuckDB 中的查询
    stored_df = store.query_daily_bars("TEST.SH")
    assert len(stored_df) == len(df)
