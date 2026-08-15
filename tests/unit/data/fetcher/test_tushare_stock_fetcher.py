from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import polars as pl

from stock.data.fetcher.tushare.stock_fetcher import TuShareStockFetcher


def test_tushare_stock_fetcher_single_symbol() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "trade_date": ["20240102"],
            "open": [1800.0],
            "high": [1820.0],
            "low": [1790.0],
            "close": [1810.0],
            "vol": [10000.0],
            "amount": [181000.0],
        }
    )
    fetcher = TuShareStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df("600519.SH", date(2024, 1, 2), date(2024, 1, 2))
    assert not df.is_empty()
    assert df["ts_code"][0] == "600519.SH"

    bars = fetcher.fetch_daily_bars("600519.SH", date(2024, 1, 2), date(2024, 1, 2))
    assert len(bars) == 1
    assert bars[0].close == 1810.0


def test_tushare_stock_fetcher_index_unsupported_skips() -> None:
    mock_client = MagicMock()
    fetcher = TuShareStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        symbol="999999.SH",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        endpoint="index_dailybasic",
    )
    assert df.is_empty()
    mock_client.query.assert_not_called()


def test_tushare_stock_fetcher_margin_exchange_split() -> None:
    mock_client = MagicMock()
    mock_client.query.side_effect = [
        pd.DataFrame({"trade_date": ["20240102"], "rzye": [100.0], "exchange_id": ["SSE"]}),
        pd.DataFrame({"trade_date": ["20240102"], "rzye": [200.0], "exchange_id": ["SZSE"]}),
        pd.DataFrame({"trade_date": ["20240102"], "rzye": [50.0], "exchange_id": ["BSE"]}),
    ]
    fetcher = TuShareStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        symbol="",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        endpoint="margin",
    )
    assert len(df) == 3


def test_tushare_stock_fetcher_trade_cal() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "cal_date": ["20240102", "20240103"],
            "is_open": ["1", "1"],
        }
    )
    fetcher = TuShareStockFetcher(client=mock_client)
    trade_dates = fetcher.fetch_trade_cal(date(2024, 1, 1), date(2024, 1, 3))
    assert trade_dates == [date(2024, 1, 2), date(2024, 1, 3)]


def test_tushare_stock_fetcher_non_symbol_endpoint_does_not_inject_symbol() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240102"],
            "suspend_type": ["S"],
        }
    )
    fetcher = TuShareStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        symbol="suspend_d",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        endpoint="suspend_d",
    )
    assert "ts_code" in df.columns
    assert "symbol" not in df.columns


def test_tushare_stock_fetcher_trade_cal_local_catalog(monkeypatch: Any) -> None:
    mock_df = pl.DataFrame({
        "cal_date": ["20240102", "20240103"],
        "is_open": [1, 1],
    })
    mock_cat = MagicMock()
    mock_cat.load_dataset.return_value = mock_df

    monkeypatch.setattr("stock.data.catalog.DataCatalog", lambda **kwargs: mock_cat)

    mock_client = MagicMock()
    fetcher = TuShareStockFetcher(client=mock_client)
    trade_dates = fetcher.fetch_trade_cal(date(2024, 1, 2), date(2024, 1, 3))
    assert trade_dates == [date(2024, 1, 2), date(2024, 1, 3)]
    mock_client.query.assert_not_called()


def test_tushare_stock_fetcher_trade_cal_single_request() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame({
        "cal_date": ["20240102"],
        "is_open": [1],
        "exchange": ["SSE"],
    })
    fetcher = TuShareStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        symbol="",
        start_date=date(1990, 1, 1),
        end_date=date(2026, 1, 1),
        endpoint="trade_cal",
    )
    assert len(df) == 1
    assert mock_client.query.call_count == 1
    _, kwargs = mock_client.query.call_args
    assert kwargs["start_date"] == "19900101"
    assert kwargs["end_date"] == "20260101"
    assert "trade_date" not in kwargs
