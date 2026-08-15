from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from stock.data.fetcher.fred.global_fetcher import FredDataFetcher


def test_fred_data_fetcher_single_series() -> None:
    mock_client = MagicMock()
    mock_client.fetch_series_raw.return_value = pd.DataFrame(
        {
            "DATE": ["2024-01-01", "2024-01-02"],
            "FEDFUNDS": [5.33, 5.33],
        }
    )
    fetcher = FredDataFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        symbol="FEDFUNDS", start_date=date(2024, 1, 1), end_date=date(2024, 1, 2)
    )
    assert not df.is_empty()
    assert df["symbol"][0] == "FEDFUNDS"
    assert df["close"][0] == 5.33


def test_fred_data_fetcher_macro_indicators() -> None:
    mock_client = MagicMock()
    mock_client.fetch_series_raw.return_value = pd.DataFrame(
        {
            "DATE": ["2024-01-01"],
            "FEDFUNDS": [5.33],
        }
    )
    fetcher = FredDataFetcher(client=mock_client)
    df = fetcher.fetch_macro_indicators_df(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
        series_ids=["FEDFUNDS"],
    )
    assert not df.is_empty()
    assert len(df) == 1


def test_fred_macro_endpoint_respects_explicit_symbol() -> None:
    mock_client = MagicMock()

    def fetch_series_raw(series_id: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "DATE": ["2024-01-01"],
                series_id: [3.7],
            }
        )

    mock_client.fetch_series_raw.side_effect = fetch_series_raw
    fetcher = FredDataFetcher(client=mock_client)

    df = fetcher.fetch_daily_bars_df(
        symbol="UNRATE",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
        endpoint="macro_indicators",
    )

    assert df["symbol"].to_list() == ["UNRATE"]
    mock_client.fetch_series_raw.assert_called_once_with("UNRATE")
