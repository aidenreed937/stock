"""历史数据回填调度器单元测试。"""

from datetime import date

import pytest

from stock.data.backfill import HistoricalBackfiller
from stock.data.fetcher.mock import MockDataFetcher
from stock.data.pipeline import MarketDataPipeline
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.data.storage.raw_store import RawDataStorage
from stock.exceptions import DataFetchError


def test_historical_backfiller_resume_and_skip(tmp_path) -> None:
    fetcher = MockDataFetcher()
    store = DuckDBMarketStore(storage_dir=tmp_path / "curated")
    raw_store = RawDataStorage(base_dir=tmp_path / "raw")
    pipeline = MarketDataPipeline(
        fetcher=fetcher, store=store, raw_store=raw_store, data_source="mock"
    )

    backfiller = HistoricalBackfiller(
        pipeline=pipeline, fetcher=fetcher, data_source="mock", endpoint="daily"
    )

    start_d = date(2026, 8, 1)  # 2026-08-01 为周六
    end_d = date(2026, 8, 5)  # 2026-08-05 为周三

    # 1. 首次运行回填
    stats = backfiller.backfill_range(start_d, end_d)
    assert stats["total_days"] == 5
    assert stats["open_days"] == 3  # 周一 8/3, 周二 8/4, 周三 8/5
    assert stats["synced_days"] == 3
    assert stats["skipped_days"] == 0

    # 2. 第二次运行：命中 RAW 缓存，断点续传自动跳过
    stats_resume = backfiller.backfill_range(start_d, end_d, force_refresh=False)
    assert stats_resume["open_days"] == 3
    assert stats_resume["skipped_days"] == 3
    assert stats_resume["synced_days"] == 0


def test_historical_backfiller_force_refresh(tmp_path) -> None:
    fetcher = MockDataFetcher()
    store = DuckDBMarketStore(storage_dir=tmp_path / "curated")
    raw_store = RawDataStorage(base_dir=tmp_path / "raw")
    pipeline = MarketDataPipeline(
        fetcher=fetcher, store=store, raw_store=raw_store, data_source="mock"
    )

    backfiller = HistoricalBackfiller(
        pipeline=pipeline, fetcher=fetcher, data_source="mock", endpoint="daily"
    )

    start_d = date(2026, 8, 3)
    end_d = date(2026, 8, 3)

    # 首次写入
    backfiller.backfill_range(start_d, end_d)

    # 强制刷新 API 覆盖
    stats_refresh = backfiller.backfill_range(start_d, end_d, force_refresh=True)
    assert stats_refresh["synced_days"] == 1
    assert stats_refresh["skipped_days"] == 0


def test_historical_backfiller_missing_trade_cal() -> None:
    class InvalidFetcher:
        pass

    backfiller = HistoricalBackfiller(fetcher=InvalidFetcher())  # type: ignore
    with pytest.raises(DataFetchError, match="未实现 fetch_trade_cal 交易日历接口"):
        backfiller.backfill_range(date(2026, 8, 1), date(2026, 8, 5))


def test_historical_backfiller_calendar_cache(tmp_path) -> None:
    fetcher = MockDataFetcher()
    store = DuckDBMarketStore(storage_dir=tmp_path / "curated")
    raw_store = RawDataStorage(base_dir=tmp_path / "raw")
    pipeline = MarketDataPipeline(
        fetcher=fetcher, store=store, raw_store=raw_store, data_source="mock"
    )

    backfiller = HistoricalBackfiller(
        pipeline=pipeline, fetcher=fetcher, data_source="mock", endpoint="daily"
    )

    start_d = date(2026, 8, 3)
    end_d = date(2026, 8, 5)

    assert (start_d, end_d) not in backfiller._calendar_cache
    backfiller.backfill_range(start_d, end_d)
    assert (start_d, end_d) in backfiller._calendar_cache
    assert len(backfiller._calendar_cache[(start_d, end_d)]) == 3
