from datetime import date
import polars as pl
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.data.fetcher.mock import MockDataFetcher

def test_duckdb_store(tmp_path, mock_fetcher: MockDataFetcher) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path)
    df = mock_fetcher.fetch_daily_bars_df("TEST.SH", date(2026, 1, 1), date(2026, 1, 15))
    df = df.with_columns(pl.lit("TEST.SH").alias("symbol"))

    file_path = store.save_market_data("daily", date(2026, 1, 15), df)
    assert file_path.exists()

    queried_df = store.query_daily_bars("TEST.SH")
    assert len(queried_df) == len(df)
