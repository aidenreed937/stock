from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from stock.data.fetcher.fred.client import FredClient
from stock.data.fetcher.fred.factory import create_fred_fetcher
from stock.data.fetcher.fred.global_fetcher import FredDataFetcher


def test_fred_client() -> None:
    client = FredClient()
    mock_df = pd.DataFrame({"observation_date": ["2026-08-10"], "FEDFUNDS": [4.5]})

    with patch.object(client.session, "get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = "observation_date,FEDFUNDS\n2026-08-10,4.5"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        df = client.fetch_series_raw("FEDFUNDS")
        assert not df.empty
        assert "DATE" in df.columns
        assert df["FEDFUNDS"].iloc[0] == 4.5


def test_fred_fetcher() -> None:
    fetcher = create_fred_fetcher()
    assert isinstance(fetcher, FredDataFetcher)

    mock_df = pd.DataFrame({"observation_date": ["2026-08-10"], "FEDFUNDS": [4.5]})

    with patch.object(fetcher.client.session, "get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = "observation_date,FEDFUNDS\n2026-08-10,4.5"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        pl_df = fetcher.fetch_series_df("FEDFUNDS", date(2026, 8, 1), date(2026, 8, 12))
        assert not pl_df.is_empty()
        assert pl_df["symbol"][0] == "FEDFUNDS"
        assert pl_df["value"][0] == 4.5
        assert pl_df["data_source"][0] == "fred"
