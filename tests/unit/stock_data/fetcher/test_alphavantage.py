from datetime import date
from unittest.mock import MagicMock

import polars as pl
import pytest

from stock_data.fetcher.alphavantage.client import AlphaVantageClient, AlphaVantageError
from stock_data.fetcher.alphavantage.global_fetcher import AlphaVantageDataFetcher


def _series() -> dict[str, dict[str, str]]:
    return {
        "2026-08-14": {
            "1. open": "7.1234",
            "2. high": "7.2345",
            "3. low": "7.0123",
            "4. close": "7.2000",
        },
        "2026-08-13": {
            "1. open": "7.1000",
            "2. high": "7.1800",
            "3. low": "7.0500",
            "4. close": "7.1200",
        },
    }


def test_fetch_fx_daily_maps_cnh_and_clips_dates() -> None:
    client = MagicMock()
    client.fetch_fx_daily_raw.return_value = _series()
    fetcher = AlphaVantageDataFetcher(client=client)

    frame = fetcher.fetch_daily_bars_df(
        "CNH=X", date(2026, 8, 14), date(2026, 8, 14), endpoint="FX_DAILY"
    )

    client.fetch_fx_daily_raw.assert_called_once_with("USD", "CNH")
    assert frame.schema == {
        "symbol": pl.String,
        "trade_date": pl.Date,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "volume": pl.Float64,
        "amount": pl.Float64,
    }
    assert frame["symbol"].to_list() == ["CNH=X"]
    assert frame["trade_date"].to_list() == [date(2026, 8, 14)]
    assert frame["volume"].to_list() == [0.0]


def test_fetcher_rejects_unknown_fx_symbol() -> None:
    fetcher = AlphaVantageDataFetcher(client=MagicMock())

    with pytest.raises(ValueError, match="暂不支持"):
        fetcher.fetch_daily_bars_df("CLF", date(2026, 8, 1), date(2026, 8, 2))


def test_fetcher_rejects_unknown_endpoint() -> None:
    fetcher = AlphaVantageDataFetcher(client=MagicMock())

    with pytest.raises(ValueError, match="Unsupported"):
        fetcher.fetch_daily_bars_df(
            "CNH=X", date(2026, 8, 1), date(2026, 8, 2), endpoint="TIME_SERIES_DAILY"
        )


def test_client_requires_api_key() -> None:
    client = AlphaVantageClient(api_key="", session=MagicMock())

    with pytest.raises(AlphaVantageError, match="ALPHA_VANTAGE_API_KEY"):
        client.fetch_fx_daily_raw("USD", "CNH")


def test_client_raises_alpha_vantage_error_payload() -> None:
    response = MagicMock()
    response.json.return_value = {"Error Message": "Invalid API call."}
    session = MagicMock()
    session.get.return_value = response
    client = AlphaVantageClient(api_key="test-key", session=session, rate_limit_per_min=5)

    with pytest.raises(AlphaVantageError, match="Invalid API call"):
        client.fetch_fx_daily_raw("USD", "CNH")

    session.get.assert_called_once()


def test_client_retries_rate_limit_with_backoff() -> None:
    retry_response = MagicMock()
    retry_response.status_code = 429
    retry_response.headers = {}
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.raise_for_status.return_value = None
    success_response.json.return_value = {"Time Series FX (Daily)": _series()}
    session = MagicMock()
    session.get.side_effect = [retry_response, success_response]
    sleep_fn = MagicMock()
    client = AlphaVantageClient(
        api_key="test-key",
        session=session,
        rate_limit_per_min=5,
        max_retries=1,
        backoff_factor=0.5,
        sleep_fn=sleep_fn,
    )

    result = client.fetch_fx_daily_raw("USD", "CNH")

    assert result == _series()
    assert session.get.call_count == 2
    sleep_fn.assert_called_once_with(0.5)


def test_fetch_trade_cal_uses_weekdays() -> None:
    fetcher = AlphaVantageDataFetcher(client=MagicMock())

    assert fetcher.fetch_trade_cal(date(2026, 8, 14), date(2026, 8, 16)) == [date(2026, 8, 14)]
