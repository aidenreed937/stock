from datetime import date
from stock.data.fetcher.mock import MockDataFetcher

def test_mock_fetcher(mock_fetcher: MockDataFetcher) -> None:
    start = date(2026, 1, 1)
    end = date(2026, 1, 10)
    df = mock_fetcher.fetch_daily_bars_df("TEST", start, end)
    assert not df.is_empty()
    assert "close" in df.columns
    assert "trade_date" in df.columns
