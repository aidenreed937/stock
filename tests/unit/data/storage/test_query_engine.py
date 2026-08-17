from datetime import date
from pathlib import Path
import polars as pl

from stock_data.storage.query_engine import DuckDBQueryEngine


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
    res_hist = engine.query_history(
        [parquet_path], data_source="tushare", symbols=["000001.SZ"]
    )
    assert len(res_hist) == 2


def test_duckdb_query_engine_empty_input() -> None:
    engine = DuckDBQueryEngine()
    assert engine.query_dataset([]).is_empty()
    assert engine.query_daily_bars([], "000001.SZ", "tushare").is_empty()
    assert engine.query_history([], "tushare").is_empty()
    assert engine.query_universe_snapshots([]).is_empty()
