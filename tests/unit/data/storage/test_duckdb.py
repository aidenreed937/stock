from datetime import date, datetime, timezone

import polars as pl
import pytest

from stock.core.contracts import DatasetKey, instrument_for_symbol
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


def test_daily_query_ignores_migration_backup_with_incompatible_schema(
    tmp_path, mock_fetcher: MockDataFetcher
) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")
    df = mock_fetcher.fetch_daily_bars_df("TEST.SH", date(2026, 1, 15), date(2026, 1, 15))
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
    active_path = store.save_market_data("daily", date(2026, 1, 15), df)
    backup_path = active_path.with_name("data.bak.parquet")
    pl.DataFrame({"legacy": [1]}).write_parquet(backup_path)

    queried = store.query_daily_bars("TEST.SH")

    assert len(queried) == 1
    assert queried["symbol"].to_list() == ["TEST.SH"]


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


def test_duckdb_store_merges_datetime_columns_with_mixed_timezones(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")
    file_path = store.get_parquet_path("daily_basic", date(2026, 1, 1), market="CN")
    base = pl.DataFrame(
        {
            "symbol": ["TEST.SH"],
            "trade_date": [date(2026, 1, 1)],
            "updated_at": [datetime(2026, 1, 1, tzinfo=timezone.utc)],
            "data_source": ["mock"],
            "market": ["CN"],
        }
    )
    incoming = base.with_columns(
        [
            pl.lit(date(2026, 1, 2)).alias("trade_date"),
            pl.lit(datetime(2026, 1, 2)).alias("updated_at"),
        ]
    )
    file_path.parent.mkdir(parents=True)
    base.write_parquet(file_path)

    merged = store._merge_and_save_parquet(file_path, [incoming])

    assert len(merged) == 2
    assert merged.schema["updated_at"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_duckdb_store_deduplicates_bar_adjustment_variants(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="tushare")
    file_path = store.get_parquet_path("stock_daily_bar", date(2026, 8, 1), market="CN")
    existing = pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "trade_date": [date(2026, 8, 1)],
            "open": [1500.0],
            "high": [None],
            "low": [None],
            "close": [1505.0],
            "market": ["CN"],
            "adjustment": ["normal"],
            "data_source": ["tushare"],
            "updated_at": [datetime(2026, 8, 12, tzinfo=timezone.utc)],
        }
    )
    incoming = existing.with_columns(
        [
            pl.lit(1510.0).alias("high"),
            pl.lit(1490.0).alias("low"),
            pl.lit("raw").alias("adjustment"),
            pl.lit(datetime(2026, 8, 13, tzinfo=timezone.utc)).alias("updated_at"),
        ]
    )
    file_path.parent.mkdir(parents=True)
    existing.write_parquet(file_path)

    merged = store._merge_and_save_parquet(file_path, [incoming])

    assert len(merged) == 1
    assert merged["adjustment"].to_list() == ["raw"]
    assert merged["high"].to_list() == [1510.0]
    assert merged["low"].to_list() == [1490.0]


def test_duckdb_store_deduplicates_fund_bar_adjustment_variants(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="tushare")
    file_path = store.get_parquet_path("fund_daily", date(2026, 7, 28), market="CN")
    existing = pl.DataFrame(
        {
            "symbol": ["159017.SZ"],
            "trade_date": [date(2026, 7, 28)],
            "market": ["CN"],
            "open": [0.897],
            "high": [0.889],
            "low": [0.901],
            "close": [0.858],
            "adjustment": ["normal"],
            "data_source": ["tushare"],
            "updated_at": [datetime(2026, 8, 12, tzinfo=timezone.utc)],
        }
    )
    incoming = existing.with_columns(
        [
            pl.lit(0.911).alias("high"),
            pl.lit(0.889).alias("low"),
            pl.lit("raw").alias("adjustment"),
            pl.lit(datetime(2026, 8, 13, tzinfo=timezone.utc)).alias("updated_at"),
        ]
    )
    file_path.parent.mkdir(parents=True)
    existing.write_parquet(file_path)

    merged = store._merge_and_save_parquet(file_path, [incoming])

    assert len(merged) == 1
    assert merged["adjustment"].to_list() == ["raw"]
    assert merged["high"].to_list() == [0.911]


def test_duckdb_store_merges_source_symbol_alias_into_standard_column(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")
    file_path = store.get_parquet_path("daily_basic", date(2026, 7, 1), market="CN")
    existing = pl.DataFrame(
        {
            "symbol": ["A"],
            "trade_date": [date(2026, 7, 30)],
            "data_source": ["mock"],
            "market": ["CN"],
        }
    )
    incoming = pl.DataFrame(
        {
            "ts_code": ["B"],
            "trade_date": [date(2026, 7, 31)],
            "data_source": ["mock"],
            "market": ["CN"],
        }
    )
    file_path.parent.mkdir(parents=True)
    existing.write_parquet(file_path)

    merged = store._merge_and_save_parquet(file_path, [incoming])

    assert merged["symbol"].to_list() == ["A", "B"]
    assert "ts_code" not in merged.columns


def test_duckdb_store_preserves_quarterly_and_event_rows(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="tushare")
    base = {
        "symbol": ["600519.SH", "600519.SH"],
        "data_source": ["tushare", "tushare"],
        "market": ["CN", "CN"],
    }

    quarterly = pl.DataFrame(
        {
            **base,
            "end_date": ["20240331", "20240630"],
            "value": [1.0, 2.0],
        }
    )
    quarterly_path = store.get_parquet_path("income", date(2026, 8, 12), market="CN")
    quarterly_path.parent.mkdir(parents=True)
    merged_quarterly = store._merge_and_save_parquet(quarterly_path, [quarterly])
    assert len(merged_quarterly) == 2

    events = pl.DataFrame(
        {
            "symbol": ["600519.SH", "600519.SH"],
            "suspend_date": ["20260801", "20260802"],
            "market": ["CN", "CN"],
            "data_source": ["tushare", "tushare"],
        }
    )
    events_path = store.get_parquet_path("suspend_d", date(2026, 8, 12), market="CN")
    events_path.parent.mkdir(parents=True)
    merged_events = store._merge_and_save_parquet(events_path, [events])
    assert len(merged_events) == 2

    top10 = pl.DataFrame(
        {
            "symbol": ["600519.SH", "600519.SH"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "market_type": ["1", "2"],
            "market": ["CN", "CN"],
            "data_source": ["tushare", "tushare"],
        }
    )
    top10_path = store.get_parquet_path("hsgt_top10", date(2026, 8, 12), market="CN")
    top10_path.parent.mkdir(parents=True)
    merged_top10 = store._merge_and_save_parquet(top10_path, [top10])
    assert len(merged_top10) == 2


def test_duckdb_store_partitions_financial_rows_by_report_end_date(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="tushare")
    frame = pl.DataFrame(
        {
            "symbol": ["600519.SH", "600519.SH"],
            "end_date": ["20240331", "20240630"],
            "revenue": [1.0, 2.0],
            "data_source": ["tushare", "tushare"],
            "market": ["CN", "CN"],
        }
    )

    store.save_market_data("income", date(2026, 8, 12), frame)

    march_path = store.get_parquet_path("income", date(2024, 3, 1), market="CN")
    june_path = store.get_parquet_path("income", date(2024, 6, 1), market="CN")
    fallback_path = store.get_parquet_path("income", date(2026, 8, 12), market="CN")
    assert march_path.exists()
    assert june_path.exists()
    assert not fallback_path.exists()
    assert pl.read_parquet(march_path)["end_date"].to_list() == ["20240331"]
    assert pl.read_parquet(june_path)["end_date"].to_list() == ["20240630"]


def test_duckdb_store_routes_mixed_date_formats_without_dropping_rows(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")
    frame = pl.DataFrame(
        {
            "symbol": ["A", "B"],
            "trade_date": ["20260812", "2026-08-13"],
            "value": [1.0, 2.0],
            "data_source": ["mock", "mock"],
            "market": ["CN", "CN"],
        }
    )

    store.save_market_data("daily_basic", date(2026, 8, 13), frame)

    path = store.get_parquet_path("daily_basic", date(2026, 8, 1), market="CN")
    saved = pl.read_parquet(path)
    assert len(saved) == 2


def test_duckdb_store_prefers_source_symbol_over_placeholder(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")
    file_path = store.get_parquet_path("adj_factor", date(2026, 8, 1), market="CN")
    existing = pl.DataFrame(
        {
            "symbol": ["ADJ_FACTOR"],
            "trade_date": [date(2026, 8, 1)],
            "data_source": ["mock"],
            "market": ["CN"],
        }
    )
    incoming = pl.DataFrame(
        {
            "symbol": ["ADJ_FACTOR"],
            "ts_code": ["600000.SH"],
            "trade_date": [date(2026, 8, 2)],
            "data_source": ["mock"],
            "market": ["CN"],
        }
    )
    file_path.parent.mkdir(parents=True)
    existing.write_parquet(file_path)

    merged = store._merge_and_save_parquet(file_path, [incoming])

    assert merged["symbol"].to_list() == ["ADJ_FACTOR", "600000.SH"]


def test_duckdb_store_removes_legacy_hk_hold_symbol_when_source_code_is_qualified(
    tmp_path,
) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="tushare")
    file_path = store.get_parquet_path("hk_hold", date(2026, 6, 30), market="CN")
    existing = pl.DataFrame(
        {
            "symbol": ["90519"],
            "trade_date": [date(2026, 6, 30)],
            "data_source": ["tushare"],
            "market": ["CN"],
        }
    )
    incoming = existing.with_columns(pl.lit("600519.SH").alias("symbol"))
    file_path.parent.mkdir(parents=True)
    existing.write_parquet(file_path)

    merged = store._merge_and_save_parquet(file_path, [incoming])

    assert merged["symbol"].to_list() == ["600519.SH"]


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

    # 6. 校验历史早期（如 1991 年）全市场阈值设定
    df_early = pl.DataFrame(
        {
            "symbol": ["STK1.SH", "STK2.SH", "STK3.SH", "STK4.SH", "STK5.SH", "STK6.SH"],
            "trade_date": [date(1991, 12, 18)] * 6,
            "open": [10.0] * 6,
            "high": [11.0] * 6,
            "low": [9.0] * 6,
            "close": [10.5] * 6,
            "volume": [1000.0] * 6,
            "amount": [10500.0] * 6,
            "pre_close": [10.0] * 6,
            "change": [0.5] * 6,
            "pct_chg": [5.0] * 6,
            "data_source": ["mock"] * 6,
            "market": ["CN"] * 6,
            "exchange": ["SSE"] * 6,
            "currency": ["CNY"] * 6,
            "adjustment": ["raw"] * 6,
            "schema_version": ["v1"] * 6,
        }
    )
    store.save_market_data("daily", date(1991, 12, 18), df_early)
    if hasattr(store, "_curated_cache"):
        delattr(store, "_curated_cache")
    # 对于 1991 年，6 只股票已超过 min_symbols (5 只)，判定为已归档，应返回 True
    assert store.has_curated("daily", date(1991, 12, 18), symbol=None)


def test_query_universe_snapshots(tmp_path) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path, data_source="mock")
    assert store.query_universe_snapshots().is_empty()

    snap_dir = store.storage_dir / "universe_snapshots" / "as_of_date=2026-08-12"
    snap_dir.mkdir(parents=True, exist_ok=True)
    df_snap = pl.DataFrame({
        "as_of_date": ["2026-08-12"],
        "symbol": ["600519"],
        "ts_code": ["600519.SH"],
    })
    df_snap.write_parquet(snap_dir / "snapshot.parquet")

    res = store.query_universe_snapshots()
    assert len(res) == 1
    assert res["symbol"][0] == "600519"

    res_filtered = store.query_universe_snapshots(as_of_date="2026-08-12")
    assert len(res_filtered) == 1
