from datetime import date

import pytest
from pydantic import ValidationError

from stock.data.fetcher.example import MockDataFetcher
from stock.data.storage.duckdb_store import DuckDBMarketStore
from stock.models.market import DailyBar


def test_daily_bar_validation(sample_daily_bar: DailyBar) -> None:
    assert sample_daily_bar.symbol == "600000.SH"
    assert sample_daily_bar.high >= sample_daily_bar.low


def test_daily_bar_invalid_high() -> None:
    with pytest.raises(ValidationError):
        DailyBar(
            symbol="600000.SH",
            trade_date=date(2026, 1, 5),
            open=10.0,
            high=9.0,  # 错误：最高价低于开盘价
            low=8.0,
            close=9.5,
            volume=100.0,
        )


def test_mock_fetcher(mock_fetcher: MockDataFetcher) -> None:
    start = date(2026, 1, 1)
    end = date(2026, 1, 10)
    df = mock_fetcher.fetch_daily_bars_df("TEST", start, end)
    assert not df.is_empty()
    assert "close" in df.columns
    assert "trade_date" in df.columns


def test_duckdb_store(tmp_path, mock_fetcher: MockDataFetcher) -> None:
    store = DuckDBMarketStore(storage_dir=tmp_path)
    df = mock_fetcher.fetch_daily_bars_df("TEST.SH", date(2026, 1, 1), date(2026, 1, 15))

    file_path = store.save_daily_bars("TEST.SH", df)
    assert file_path.exists()

    queried_df = store.query_daily_bars("TEST.SH")
    assert len(queried_df) == len(df)
