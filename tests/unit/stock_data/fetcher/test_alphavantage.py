import json
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


def _stock_series() -> dict[str, dict[str, str]]:
    return {
        "2026-08-14": {
            "1. open": "220.00",
            "2. high": "223.00",
            "3. low": "219.00",
            "4. close": "222.00",
            "5. volume": "1000",
        },
        "2026-08-13": {
            "1. open": "218.00",
            "2. high": "221.00",
            "3. low": "217.00",
            "4. close": "220.00",
            "5. volume": "900",
        },
    }


def test_fetch_stock_daily_maps_ohlcv_and_computes_amount() -> None:
    client = MagicMock()
    client.fetch_daily_raw.return_value = {"Time Series (Daily)": _stock_series()}
    fetcher = AlphaVantageDataFetcher(client=client)

    frame = fetcher.fetch_daily_bars_df(
        "AAPL", date(2026, 8, 14), date(2026, 8, 14), endpoint="TIME_SERIES_DAILY"
    )

    client.fetch_daily_raw.assert_called_once_with("AAPL")
    assert frame["symbol"].to_list() == ["AAPL"]
    assert frame["trade_date"].to_list() == [date(2026, 8, 14)]
    assert frame["volume"].to_list() == [1000.0]
    assert frame["amount"].to_list() == [222000.0]


def test_fetch_company_overview_normalizes_snapshot_fields() -> None:
    client = MagicMock()
    client.fetch_company_overview_raw.return_value = {
        "Symbol": "AAPL",
        "Name": "Apple Inc.",
        "Exchange": "NASDAQ",
        "LatestQuarter": "2026-06-30",
        "MarketCapitalization": "3000000000000",
        "PERatio": "32.5",
    }
    fetcher = AlphaVantageDataFetcher(client=client)

    frame = fetcher.fetch_daily_bars_df(
        "AAPL", date(2026, 1, 1), date(2026, 10, 1), endpoint="OVERVIEW"
    )

    client.fetch_company_overview_raw.assert_called_once_with("AAPL")
    assert frame["symbol"].to_list() == ["AAPL"]
    assert frame["name"].to_list() == ["Apple Inc."]
    assert frame["market_capitalization"].to_list() == [3_000_000_000_000.0]
    assert frame["pe_ratio"].to_list() == [32.5]
    assert frame["as_of_date"].to_list() == ["2026-06-30"]


def test_fetch_earnings_keeps_annual_and_quarterly_rows() -> None:
    client = MagicMock()
    client.fetch_earnings_raw.return_value = {
        "symbol": "MSFT",
        "annualEarnings": [{"fiscalDateEnding": "2025-06-30", "reportedEPS": "12.10"}],
        "quarterlyEarnings": [
            {
                "fiscalDateEnding": "2026-06-30",
                "reportedDate": "2026-07-30",
                "reportedEPS": "3.65",
                "estimatedEPS": "3.55",
                "surprisePercentage": "2.82",
            }
        ],
    }
    fetcher = AlphaVantageDataFetcher(client=client)

    frame = fetcher.fetch_daily_bars_df(
        "MSFT", date(2025, 1, 1), date(2026, 10, 1), endpoint="EARNINGS"
    )

    assert frame["report_type"].to_list() == ["annual", "quarterly"]
    assert frame["reported_eps"].to_list() == [12.1, 3.65]
    assert frame["estimated_eps"].to_list() == [None, 3.55]
    assert frame["surprise_percentage"].to_list() == [None, 2.82]


def test_fetch_statement_maps_alpha_vantage_reports() -> None:
    client = MagicMock()
    client.fetch_statement_raw.return_value = {
        "symbol": "NVDA",
        "annualReports": [
            {
                "fiscalDateEnding": "2025-01-26",
                "reportedCurrency": "USD",
                "totalRevenue": "130497000000",
            }
        ],
        "quarterlyReports": [
            {
                "fiscalDateEnding": "2026-07-27",
                "reportedCurrency": "USD",
                "totalRevenue": "46743000000",
            }
        ],
    }
    fetcher = AlphaVantageDataFetcher(client=client)

    frame = fetcher.fetch_daily_bars_df(
        "NVDA", date(2025, 1, 1), date(2026, 10, 1), endpoint="INCOME_STATEMENT"
    )

    client.fetch_statement_raw.assert_called_once_with("NVDA", "financials")
    assert frame["report_type"].to_list() == ["annual", "quarterly"]
    assert frame["total_revenue"].to_list() == [130497000000.0, 46743000000.0]


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
            "CNH=X", date(2026, 8, 1), date(2026, 8, 2), endpoint="UNKNOWN_ENDPOINT"
        )


def test_client_requires_api_key() -> None:
    client = AlphaVantageClient(api_key="", session=MagicMock())

    with pytest.raises(AlphaVantageError, match="ALPHA_VANTAGE_API_KEY"):
        client.fetch_fx_daily_raw("USD", "CNH")


def test_client_raises_alpha_vantage_error_payload(tmp_path) -> None:
    response = MagicMock()
    response.json.return_value = {"Error Message": "Invalid API call."}
    session = MagicMock()
    session.get.return_value = response
    client = AlphaVantageClient(
        api_key="test-key",
        session=session,
        rate_limit_per_min=5,
        min_request_interval=0,
        usage_file=tmp_path / "usage.json",
    )

    with pytest.raises(AlphaVantageError, match="Invalid API call"):
        client.fetch_fx_daily_raw("USD", "CNH")

    session.get.assert_called_once()


def test_client_retries_rate_limit_with_backoff(tmp_path) -> None:
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
        min_request_interval=0,
        sleep_fn=sleep_fn,
        usage_file=tmp_path / "usage.json",
    )

    result = client.fetch_fx_daily_raw("USD", "CNH")

    assert result == _series()
    assert session.get.call_count == 2
    sleep_fn.assert_called_once_with(0.5)


def test_client_counts_retries_once_and_does_not_exhaust_frequency_key(tmp_path) -> None:
    frequency_response = MagicMock()
    frequency_response.status_code = 200
    frequency_response.raise_for_status.return_value = None
    frequency_response.json.return_value = {
        "Note": "The standard API call frequency is 5 requests per minute."
    }
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.raise_for_status.return_value = None
    success_response.json.return_value = {"Time Series FX (Daily)": _series()}
    session = MagicMock()
    session.get.side_effect = [frequency_response, success_response]
    sleep_fn = MagicMock()
    usage_file = tmp_path / "usage.json"
    client = AlphaVantageClient(
        api_key="test-key",
        session=session,
        max_retries=1,
        min_request_interval=0,
        sleep_fn=sleep_fn,
        usage_file=usage_file,
    )

    assert client.fetch_fx_daily_raw("USD", "CNH") == _series()

    usage = json.loads(usage_file.read_text(encoding="utf-8"))
    assert list(usage["counts"].values()) == [1]
    assert session.get.call_count == 2


def test_client_distinguishes_frequency_message_with_daily_limit_text() -> None:
    frequency_message = (
        "Please consider spreading out your free API requests more sparingly "
        "(1 request per second). The free key rate limit is 25 requests per day."
    )
    daily_message = "25 requests per day limit reached; please use a premium plan"

    assert not AlphaVantageClient._is_daily_quota_message(frequency_message)
    assert AlphaVantageClient._is_daily_quota_message(daily_message)


def test_client_enforces_minimum_request_interval(tmp_path) -> None:
    sleep_fn = MagicMock()
    client = AlphaVantageClient(
        api_key="test-key",
        session=MagicMock(),
        min_request_interval=1.05,
        sleep_fn=sleep_fn,
        usage_file=tmp_path / "usage.json",
    )

    client._acquire_request_slot("test-key")
    client._acquire_request_slot("test-key")

    sleep_fn.assert_called_once()
    assert 1.0 <= sleep_fn.call_args.args[0] <= 1.05


def test_client_switches_to_backup_key_after_daily_quota_message(tmp_path) -> None:
    quota_response = MagicMock()
    quota_response.status_code = 200
    quota_response.raise_for_status.return_value = None
    quota_response.json.return_value = {
        "Note": "25 requests per day limit reached; please use a premium plan"
    }
    success_response = MagicMock()
    success_response.status_code = 200
    success_response.raise_for_status.return_value = None
    success_response.json.return_value = {"Time Series FX (Daily)": _series()}
    session = MagicMock()
    session.get.side_effect = [quota_response, success_response]
    client = AlphaVantageClient(
        api_keys=["key-primary", "key-backup"],
        session=session,
        max_retries=0,
        daily_limit=25,
        min_request_interval=0,
        usage_file=tmp_path / "usage.json",
    )

    result = client.fetch_fx_daily_raw("USD", "CNH")

    assert result == _series()
    assert [call.kwargs["params"]["apikey"] for call in session.get.call_args_list] == [
        "key-primary",
        "key-backup",
    ]
    assert "key-primary" not in (tmp_path / "usage.json").read_text(encoding="utf-8")


def test_client_enforces_daily_limit_per_key(tmp_path) -> None:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {"Time Series FX (Daily)": _series()}
    session = MagicMock()
    session.get.return_value = response
    client = AlphaVantageClient(
        api_keys=["key-primary", "key-backup"],
        session=session,
        max_retries=0,
        daily_limit=1,
        min_request_interval=0,
        usage_file=tmp_path / "usage.json",
    )

    client.fetch_fx_daily_raw("USD", "CNH")
    client.fetch_fx_daily_raw("USD", "CNH")
    with pytest.raises(AlphaVantageError, match="每日额度"):
        client.fetch_fx_daily_raw("USD", "CNH")

    assert session.get.call_count == 2


def test_client_keeps_primary_key_until_failure(tmp_path) -> None:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {"Time Series FX (Daily)": _series()}
    session = MagicMock()
    session.get.return_value = response
    client = AlphaVantageClient(
        api_keys=["key-primary", "key-backup"],
        session=session,
        max_retries=0,
        daily_limit=25,
        min_request_interval=0,
        usage_file=tmp_path / "usage.json",
    )

    client.fetch_fx_daily_raw("USD", "CNH")
    client.fetch_fx_daily_raw("USD", "CNH")

    assert [call.kwargs["params"]["apikey"] for call in session.get.call_args_list] == [
        "key-primary",
        "key-primary",
    ]


def test_fetch_trade_cal_uses_weekdays() -> None:
    fetcher = AlphaVantageDataFetcher(client=MagicMock())

    assert fetcher.fetch_trade_cal(date(2026, 8, 14), date(2026, 8, 16)) == [date(2026, 8, 14)]
