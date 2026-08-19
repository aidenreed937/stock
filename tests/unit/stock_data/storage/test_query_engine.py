from datetime import date
from pathlib import Path

import polars as pl

from stock_data.storage.query_engine import DuckDBQueryEngine
from stock_data.storage.read_compat import requires_read_normalization


def test_duckdb_query_engine_basic_sql() -> None:
    engine = DuckDBQueryEngine()
    df = engine.query_by_sql("SELECT 42 AS value, 'test' AS name")
    assert len(df) == 1
    assert df["value"][0] == 42
    assert df["name"][0] == "test"


def test_duckdb_query_engine_dataset_and_daily_bars(tmp_path: Path) -> None:
    engine = DuckDBQueryEngine()
    parquet_path = tmp_path / "bars.parquet"
    df_src = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", "600519.SH"],
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-02"],
            "open": [10.0, 10.5, 1800.0],
            "high": [11.0, 11.5, 1850.0],
            "low": [9.5, 10.0, 1780.0],
            "close": [10.2, 11.0, 1820.0],
            "data_source": ["tushare", "tushare", "tushare"],
        }
    )
    df_src.write_parquet(parquet_path)

    # 1. query_dataset with symbol and date range
    res_ds = engine.query_dataset(
        [parquet_path], symbol="000001.SZ", start_date=date(2024, 1, 2), end_date=date(2024, 1, 2)
    )
    assert len(res_ds) == 1
    assert res_ds["close"][0] == 10.2

    # 2. query_daily_bars with min_price
    res_bars = engine.query_daily_bars(
        [parquet_path], symbol="600519.SH", data_source="tushare", min_price=1000.0
    )
    assert len(res_bars) == 1
    assert res_bars["close"][0] == 1820.0

    # 3. query_history with symbols filter
    res_hist = engine.query_history([parquet_path], data_source="tushare", symbols=["000001.SZ"])
    assert len(res_hist) == 2


def test_duckdb_query_engine_empty_input() -> None:
    engine = DuckDBQueryEngine()
    assert engine.query_dataset([]).is_empty()
    assert engine.query_daily_bars([], "000001.SZ", "tushare").is_empty()
    assert engine.query_history([], "tushare").is_empty()
    assert engine.query_universe_snapshots([]).is_empty()


def test_read_compat_detects_non_trade_business_date_columns(tmp_path: Path) -> None:
    path = tmp_path / "schedule.parquet"
    pl.DataFrame({"publish_date": ["20260814"], "title": ["经济数据"]}).write_parquet(path)

    assert requires_read_normalization(path, "cn_schedule")


def test_duckdb_query_engine_normalizes_legacy_identity_columns(tmp_path: Path) -> None:
    engine = DuckDBQueryEngine()
    parquet_path = tmp_path / "legacy-bars.parquet"
    pl.DataFrame(
        {
            "ts_code": ["000001.SZ", "600519.SH"],
            "date": ["2024-01-02", "2024-01-03"],
            "open": [10.0, 1800.0],
            "high": [11.0, 1850.0],
            "low": [9.5, 1780.0],
            "close": [10.2, 1820.0],
            "data_source": ["tushare", "tushare"],
        }
    ).write_parquet(parquet_path)

    result = engine.query_dataset(
        [parquet_path],
        symbol="000001.SZ",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
    )

    assert result.columns[0] == "symbol"
    assert result["symbol"].to_list() == ["000001.SZ"]
    assert result["trade_date"].to_list() == [date(2024, 1, 2)]


def test_duckdb_query_engine_normalizes_legacy_index_valuation(tmp_path: Path) -> None:
    engine = DuckDBQueryEngine()
    parquet_path = tmp_path / "legacy-index-valuation.parquet"
    pl.DataFrame(
        {
            "symbol": ["SPY"],
            "trade_date": [date(2026, 8, 14)],
            "trailing_pe": [20.0],
            "forward_pe": [19.0],
            "price_to_book": [2.0],
            "price_to_sales": [3.0],
            "dividend_yield": [1.2],
            "market_cap": [None],
            "total_assets": [500.0],
            "data_source": ["yfinance"],
        }
    ).write_parquet(parquet_path)

    result = engine.query_dataset([parquet_path], symbol="SPY", dataset_name="index_valuation")

    assert result["market_cap"].to_list() == [500.0]
    assert "total_assets" not in result.columns


def test_duckdb_query_engine_infers_dataset_from_curated_path(tmp_path: Path) -> None:
    engine = DuckDBQueryEngine()
    parquet_path = tmp_path / "market=US" / "index_valuation" / "data.parquet"
    parquet_path.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "symbol": ["SPY"],
            "trade_date": [date(2026, 8, 14)],
            "market_cap": [None],
            "total_assets": [500.0],
            "data_source": ["yfinance"],
        }
    ).write_parquet(parquet_path)

    result = engine.query_dataset([parquet_path], symbol="SPY")

    assert result["market_cap"].to_list() == [500.0]
    assert "total_assets" not in result.columns
