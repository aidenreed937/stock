from datetime import date

import polars as pl
import pytest

from stock.data.contracts import DatasetKey, instrument_for_symbol
from stock.data.fetcher.mock import MockDataFetcher
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.exceptions import DataValidationError


def test_duckdb_store(tmp_path, mock_fetcher: MockDataFetcher) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")
    df = mock_fetcher.fetch_daily_bars_df("TEST.SH", date(2026, 1, 1), date(2026, 1, 15))
    df = df.with_columns(
        [
            pl.lit("TEST.SH").alias("symbol"),
            pl.lit("mock").alias("data_source"),
            pl.lit("CN").alias("market"),
            pl.lit("SSE").alias("exchange"),
            pl.lit("CNY").alias("currency"),
            pl.lit("raw").alias("adjustment"),
            pl.lit("v1").alias("schema_version"),
        ]
    )

    file_path = store.save_market_data("daily", date(2026, 1, 15), df)
    assert file_path.exists()
    assert file_path.parent.parent.parent.parent == tmp_path / "mock"

    queried_df = store.query_daily_bars("TEST.SH")
    assert len(queried_df) == len(df)

    max_date = store.get_max_trade_date("TEST.SH")
    assert max_date == date(2026, 1, 15)
    assert store.get_max_trade_date("NON_EXISTENT") is None


def test_default_store_isolated_by_data_source(tmp_path, monkeypatch) -> None:
    from stock.config.settings import settings

    monkeypatch.setattr(settings, "curated_data_dir", tmp_path / "curated")

    tushare_store = DuckDBMarketStore(data_source="tushare")
    mock_store = DuckDBMarketStore(data_source="mock")

    assert tushare_store.storage_dir == tmp_path / "curated" / "tushare"
    assert mock_store.storage_dir == tmp_path / "curated" / "mock"


def test_pipeline_binds_explicit_store_to_source_directory(tmp_path) -> None:
    from stock.data.pipeline import MarketDataPipeline

    store = DuckDBMarketStore(storage_dir=tmp_path / "curated")
    MarketDataPipeline(
        fetcher=MockDataFetcher(),
        store=store,
        data_source="mock",
    )

    assert store.storage_dir == tmp_path / "curated" / "mock"


def test_unbound_store_rejects_reads(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path)

    with pytest.raises(DataValidationError, match="未绑定数据源"):
        store.query_history()


def test_store_rejects_mismatched_source(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="tushare")
    df = pl.DataFrame(
        {
            "symbol": ["TEST.SH"],
            "trade_date": [date(2026, 1, 15)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "amount": [10500.0],
            "data_source": ["mock"],
        }
    )
    key = DatasetKey(
        provider="tushare",
        dataset="daily_bar",
        endpoint="daily",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 15),
        instrument=instrument_for_symbol("TEST.SH", "tushare"),
    )

    with pytest.raises(DataValidationError, match="数据源不匹配"):
        store.save_dataset(key, df)


def test_store_rejects_schema_mismatch(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="tushare")
    key = DatasetKey(
        provider="tushare",
        dataset="daily_bar",
        endpoint="daily",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 15),
        instrument=instrument_for_symbol("TEST.SH", "tushare"),
    )
    complete_df = pl.DataFrame(
        {
            "symbol": ["TEST.SH"],
            "trade_date": [date(2026, 1, 15)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "amount": [10500.0],
            "pre_close": [10.2],
            "change": [0.3],
            "pct_chg": [2.94],
            "data_source": ["tushare"],
            "market": ["CN"],
            "exchange": ["SSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v1"],
        }
    )
    incomplete_df = complete_df.with_columns(pl.lit("test").alias("extra"))
    store.save_dataset(key, complete_df)

    with pytest.raises(DataValidationError, match="schema 不匹配"):
        store.save_dataset(key, incomplete_df)
