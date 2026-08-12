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
    assert "market=CN" in str(file_path)
    assert file_path.relative_to(tmp_path / "mock").parts[0] == "market=CN"

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


def test_duckdb_store_extra_branches(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")

    # Test bind_data_source mismatch
    with pytest.raises(DataValidationError, match="Curated 存储数据源不匹配"):
        store.bind_data_source("other_source")

    # Test save empty DataFrame
    file_path = store.save_market_data("daily", date(2026, 1, 15), pl.DataFrame())
    assert not file_path.exists()

    key = DatasetKey(
        provider="mock",
        dataset="daily_bar",
        endpoint="daily",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 15),
        instrument=instrument_for_symbol("TEST.SH", "mock"),
    )
    empty_dataset_path = store.save_dataset(key, pl.DataFrame())
    assert not empty_dataset_path.exists()

    # Save data for query tests
    df = pl.DataFrame(
        {
            "symbol": ["TEST.SH", "TEST.SH"],
            "trade_date": [date(2026, 1, 14), date(2026, 1, 15)],
            "open": [10.0, 20.0],
            "high": [11.0, 21.0],
            "low": [9.0, 19.0],
            "close": [10.5, 20.5],
            "volume": [1000.0, 2000.0],
            "amount": [10500.0, 41000.0],
            "pre_close": [10.0, 10.5],
            "change": [0.5, 10.0],
            "pct_chg": [5.0, 48.78],
            "data_source": ["mock", "mock"],
            "market": ["CN", "CN"],
            "exchange": ["SSE", "SSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "raw"],
            "schema_version": ["v1", "v1"],
        }
    )
    store.save_market_data("custom_endpoint", date(2026, 1, 15), df)

    # Test query_daily_bars with min_price
    filtered_df = store.query_daily_bars("TEST.SH", endpoint="custom_endpoint", min_price=15.0)
    assert len(filtered_df) == 1
    assert filtered_df["close"][0] == 20.5

    # Test query_history with custom endpoint
    hist_df = store.query_history(
        endpoint="custom_endpoint",
        start_date=date(2026, 1, 14),
        end_date=date(2026, 1, 15),
        symbols=["TEST.SH"],
    )
    assert len(hist_df) == 2


def test_duckdb_store_batch_mode(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")
    store.enable_batch_mode()

    df1 = pl.DataFrame(
        {
            "symbol": ["TEST.SH"],
            "trade_date": [date(2026, 1, 14)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [1000.0],
            "amount": [10500.0],
            "pre_close": [10.0],
            "change": [0.5],
            "pct_chg": [5.0],
            "data_source": ["mock"],
            "market": ["CN"],
            "exchange": ["SSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v1"],
        }
    )
    df2 = pl.DataFrame(
        {
            "symbol": ["TEST.SH"],
            "trade_date": [date(2026, 1, 15)],
            "open": [11.0],
            "high": [12.0],
            "low": [10.5],
            "close": [11.5],
            "volume": [1500.0],
            "amount": [17250.0],
            "pre_close": [10.5],
            "change": [1.0],
            "pct_chg": [9.52],
            "data_source": ["mock"],
            "market": ["CN"],
            "exchange": ["SSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v1"],
        }
    )

    file_path1 = store.save_market_data("daily", date(2026, 1, 14), df1)
    file_path2 = store.save_market_data("daily", date(2026, 1, 15), df2)

    # In batch mode, file should NOT exist yet
    assert not file_path1.exists()

    # Commit batch
    store.commit()

    # File should now exist and contain merged data
    assert file_path1.exists()
    queried = store.query_daily_bars("TEST.SH")
    assert len(queried) == 2

    # Calling commit again when empty should be safe
    store.commit()


def test_duckdb_store_has_curated_whole_market(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")
    # 1. 初始状态：无任何文件归档，应返回 False
    assert not store.has_curated("daily", date(2026, 1, 14), symbol=None)
    assert not store.has_curated("daily", date(2026, 1, 14), symbol="")
    assert not store.has_curated("daily", date(2026, 1, 14), symbol="TEST.SH")

    # 2. 保存极个别股票的数据（小于 1000 只，如 2 只）
    df_small = pl.DataFrame(
        {
            "symbol": ["TEST1.SH", "TEST2.SH"],
            "trade_date": [date(2026, 1, 14), date(2026, 1, 14)],
            "open": [10.0, 11.0],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.5, 11.5],
            "volume": [1000.0, 1500.0],
            "amount": [10500.0, 17250.0],
            "pre_close": [10.0, 11.0],
            "change": [0.5, 0.5],
            "pct_chg": [5.0, 4.5],
            "data_source": ["mock", "mock"],
            "market": ["CN", "CN"],
            "exchange": ["SSE", "SSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "raw"],
            "schema_version": ["v1", "v1"],
        }
    )
    store.save_market_data("daily", date(2026, 1, 14), df_small)

    # 3. 校验 has_curated 的表现：
    # - 针对特定个股查询（如 TEST1.SH），由于它已被拉取，应返回 True
    # - 针对全市场查询（symbol=None / symbol=""），由于股票数极少 (< 1000)，不判定为全市场已归档，应返回 False
    assert store.has_curated("daily", date(2026, 1, 14), symbol="TEST1.SH")
    assert not store.has_curated("daily", date(2026, 1, 14), symbol=None)
    assert not store.has_curated("daily", date(2026, 1, 14), symbol="")

    # 4. 保存大量股票的数据（例如 1005 只）
    symbols_large = [f"STK_{i:04d}.SH" for i in range(1005)]
    df_large = pl.DataFrame(
        {
            "symbol": symbols_large,
            "trade_date": [date(2026, 1, 14)] * 1005,
            "open": [10.0] * 1005,
            "high": [11.0] * 1005,
            "low": [9.0] * 1005,
            "close": [10.5] * 1005,
            "volume": [1000.0] * 1005,
            "amount": [10500.0] * 1005,
            "pre_close": [10.0] * 1005,
            "change": [0.5] * 1005,
            "pct_chg": [5.0] * 1005,
            "data_source": ["mock"] * 1005,
            "market": ["CN"] * 1005,
            "exchange": ["SSE"] * 1005,
            "currency": ["CNY"] * 1005,
            "adjustment": ["raw"] * 1005,
            "schema_version": ["v1"] * 1005,
        }
    )
    store.save_market_data("daily", date(2026, 1, 14), df_large)

    # 清空缓存使 has_curated 从磁盘重载文件
    if hasattr(store, "_curated_cache"):
        delattr(store, "_curated_cache")

    # 5. 再次校验全市场查询，股票数 > 1000，应判定为已归档，返回 True
    assert store.has_curated("daily", date(2026, 1, 14), symbol=None)
    assert store.has_curated("daily", date(2026, 1, 14), symbol="")
