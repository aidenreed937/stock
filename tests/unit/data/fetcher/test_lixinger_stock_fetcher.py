from datetime import date
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from stock.data.fetcher.lixinger.stock_fetcher import LixingerStockFetcher


def test_lixinger_stock_fetcher_single_symbol() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "stockCode": ["600519"],
            "date": ["2024-01-02T00:00:00"],
            "pe_ttm": [30.5],
            "pb": [8.2],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        symbol="600519.SH",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        endpoint="company_fundamental",
    )
    assert not df.is_empty()
    assert df["stockCode"][0] == "600519"
    assert "pe_ttm" in df.columns


def test_lixinger_stock_fetcher_constituents_expansion() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "stockCode": ["110000"],
            "constituents": [
                [
                    {"stockCode": "600519", "stockName": "贵州茅台"},
                    {"stockCode": "000858", "stockName": "五粮液"},
                ]
            ],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        symbol="",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        endpoint="sw_2021_constituents",
    )
    assert len(df) == 2
    assert "industryCode" in df.columns
    assert df["stockCode"].to_list() == ["600519", "000858"]


def test_lixinger_stock_fetcher_bars_conversion() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "stockCode": ["600519"],
            "date": ["2024-01-02T00:00:00"],
            "open": [1800.0],
            "high": [1820.0],
            "low": [1790.0],
            "close": [1810.0],
            "volume": [10000.0],
            "amount": [181000.0],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)
    bars = fetcher.fetch_daily_bars("600519.SH", date(2024, 1, 2), date(2024, 1, 2))
    assert len(bars) == 1
    assert bars[0].symbol == "600519"
    assert bars[0].close == 1810.0


def test_lixinger_stock_fetcher_trade_cal() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "date": ["2024-01-02T00:00:00", "2024-01-03T00:00:00"],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)
    dates = fetcher.fetch_trade_cal(date(2024, 1, 1), date(2024, 1, 3))
    assert dates == [date(2024, 1, 2), date(2024, 1, 3)]


def test_lixinger_stock_fetcher_chunking_for_long_range() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "stockCode": ["600519"],
            "date": ["2010-01-02T00:00:00"],
            "pe_ttm": [25.0],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        symbol="600519",
        start_date=date(2010, 1, 1),
        end_date=date(2024, 1, 1),
        endpoint="company_fundamental",
    )
    assert not df.is_empty()
    assert mock_client.query.call_count >= 2
