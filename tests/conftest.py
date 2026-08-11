from datetime import date

import pytest

from stock.data.fetcher.example import MockDataFetcher
from stock.models.market import DailyBar


@pytest.fixture
def sample_daily_bar() -> DailyBar:
    return DailyBar(
        symbol="600000.SH",
        trade_date=date(2026, 1, 5),
        open=10.0,
        high=10.5,
        low=9.8,
        close=10.2,
        volume=10000.0,
        amount=102000.0,
    )


@pytest.fixture
def mock_fetcher() -> MockDataFetcher:
    return MockDataFetcher()
