"""ETL 清洗、标准化与 Pipeline 数据流单元测试。"""

from datetime import date, timedelta
from typing import Any

import polars as pl

from stock_data.fetcher.base import BaseDataFetcher
from stock_data.governance.quality.quarantine import QuarantineStore
from stock_data.pipeline import MarketDataPipeline
from stock_data.pipeline.cleaner.bar_cleaner import BarDataCleaner
from stock_data.pipeline.normalizer.bar_normalizer import BarDataNormalizer
from stock_data.storage.duckdb_store import DuckDBMarketStore
from stock_data.storage.raw_store import RawDataStorage


class StubBarFetcher(BaseDataFetcher):
    """用于 Pipeline 流程测试的桩 Fetcher。"""

    def fetch_daily_bars(self, symbol: str, start_date: date, end_date: date):
        return []

    def fetch_daily_bars_df(
        self, symbol: str, start_date: date, end_date: date, endpoint: str = "daily", **kwargs: Any
    ) -> pl.DataFrame:
        dates: list[date] = []
        curr = start_date
        while curr <= end_date:
            dates.append(curr)
            curr += timedelta(days=1)
        prices = [10.0 + i * 0.1 for i in range(len(dates))]
        return pl.DataFrame(
            {
                "ts_code": [symbol] * len(dates),
                "trade_date": [d.strftime("%Y%m%d") for d in dates],
                "open": prices,
                "high": [p + 0.5 for p in prices],
                "low": [p - 0.5 for p in prices],
                "close": prices,
                "vol": [1000.0] * len(dates),
                "amount": [p * 1000.0 for p in prices],
            }
        )

    def fetch_trade_cal(self, start_date: date, end_date: date) -> list[date]:
        curr = start_date
        cal: list[date] = []
        while curr <= end_date:
            cal.append(curr)
            curr += timedelta(days=1)
        return cal


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
    fetcher = StubBarFetcher()
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


def test_market_data_pipeline_quarantines_rejected_rows(tmp_path, monkeypatch) -> None:
    class DirtyFetcher:
        def fetch_daily_bars(self, symbol, start_date, end_date):
            return []

        def fetch_daily_bars_df(self, symbol, start_date, end_date, endpoint="daily"):
            return pl.DataFrame(
                {
                    "ts_code": ["600000.SH", "000001.SZ"],
                    "trade_date": ["20260812", "20260812"],
                    "open": [10.0, 0.0],
                    "high": [11.0, 0.0],
                    "low": [9.0, 0.0],
                    "close": [10.5, 0.0],
                    "vol": [100.0, 100.0],
                    "amount": [105.0, 0.0],
                }
            )

    monkeypatch.setattr(
        "stock_data.pipeline.stages.QuarantineStore",
        lambda: QuarantineStore(tmp_path / "quarantine"),
    )
    store = DuckDBMarketStore(storage_dir=tmp_path / "curated")
    raw_store = RawDataStorage(base_dir=tmp_path / "raw")
    pipeline = MarketDataPipeline(
        fetcher=DirtyFetcher(),
        store=store,
        raw_store=raw_store,
        data_source="tushare",
        endpoint="stock_daily_bar",
    )

    df = pipeline.sync_daily_bars("600000.SH", date(2026, 8, 12), date(2026, 8, 12))

    assert len(df) == 1
    quarantined = pl.read_parquet(
        tmp_path / "quarantine" / "endpoint=stock_daily_bar" / "records.parquet"
    )
    assert quarantined["ts_code"].to_list() == ["000001.SZ"]


def test_macro_pipeline_sync_does_not_clip_history(tmp_path) -> None:
    class StubMacroFetcher:
        def fetch_daily_bars_df(self, symbol, start_date, end_date, endpoint="cn_cpi"):
            return pl.DataFrame(
                {
                    "month": ["202301", "202302", "202303", "202304"],
                    "cpi": [101.0, 101.5, 101.8, 102.0],
                }
            )

    store = DuckDBMarketStore(storage_dir=tmp_path / "curated")
    raw_store = RawDataStorage(base_dir=tmp_path / "raw")
    pipeline = MarketDataPipeline(
        fetcher=StubMacroFetcher(),
        store=store,
        raw_store=raw_store,
        data_source="tushare",
        endpoint="cn_cpi",
    )

    # 即使传入单日请求区间，由于是宏观免分区接口，也不应丢弃其余历史月份
    df = pipeline.sync_daily_bars("cn_cpi", date(2023, 4, 1), date(2023, 4, 30))
    assert len(df) == 4
    assert set(df["month"].to_list()) == {"202301", "202302", "202303", "202304"}
