from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from stock.data.fetcher.yfinance.client import YFinanceClient
from stock.data.fetcher.yfinance.global_fetcher import YFinanceDataFetcher
from stock.data.fetcher.yfinance.factory import create_yfinance_pipeline


def test_yfinance_fetcher() -> None:
    # 构造模拟的 pandas DataFrame 返回值
    mock_df = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1000.0, 2000.0],
        },
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )

    client = YFinanceClient(proxy="http://mock-proxy")
    fetcher = YFinanceDataFetcher(client=client)

    with patch("yfinance.Ticker") as mock_ticker_class:
        mock_ticker_instance = MagicMock()
        mock_ticker_instance.history.return_value = mock_df
        mock_ticker_class.return_value = mock_ticker_instance

        bars = fetcher.fetch_daily_bars("^GSPC", date(2026, 1, 1), date(2026, 1, 2))

        # 验证调用参数
        assert mock_ticker_class.call_count == 1
        assert mock_ticker_class.call_args[0][0] == "^GSPC"
        mock_ticker_instance.history.assert_called_once_with(
            start="2026-01-01",
            end="2026-01-03",  # end_date + 1 天 (不含)
            interval="1d",
        )

        # 验证结果解析
        assert len(bars) == 2
        assert bars[0].close == 101.0
        assert bars[0].trade_date == date(2026, 1, 1)
        assert bars[1].volume == 2000.0
        assert bars[1].amount == 204000.0  # 2000 * 102.0


def test_yfinance_fetcher_empty() -> None:
    client = YFinanceClient()
    fetcher = YFinanceDataFetcher(client=client)

    with patch("yfinance.Ticker") as mock_ticker_class:
        mock_ticker_instance = MagicMock()
        mock_ticker_instance.history.return_value = pd.DataFrame()
        mock_ticker_class.return_value = mock_ticker_instance

        bars = fetcher.fetch_daily_bars("^GSPC", date(2026, 1, 1), date(2026, 1, 2))
        assert len(bars) == 0

        df = fetcher.fetch_daily_bars_df("^GSPC", date(2026, 1, 1), date(2026, 1, 2))
        assert df.is_empty()


def test_create_yfinance_pipeline() -> None:
    pipeline = create_yfinance_pipeline(proxy="http://some-proxy")
    assert pipeline.data_source == "yfinance"
    assert pipeline.endpoint == "history"
    assert isinstance(pipeline.fetcher, YFinanceDataFetcher)
    assert pipeline.fetcher.client.proxy == "http://some-proxy"


def test_fetch_index_valuations() -> None:
    client = YFinanceClient()
    fetcher = YFinanceDataFetcher(client=client)

    mock_info = {
        "trailingPE": 25.5,
        "forwardPE": 22.0,
        "priceToBook": 1.8,
        "priceToSalesTrailing12Months": 3.2,
        "yield": 0.012,
        "totalAssets": 500000000.0,
    }

    with patch("yfinance.Ticker") as mock_ticker_class:
        mock_ticker_instance = MagicMock()
        mock_ticker_instance.info = mock_info
        mock_ticker_class.return_value = mock_ticker_instance

        df = fetcher.fetch_index_valuations_df(etf_map={"SPY": "^GSPC"}, target_date=date(2026, 8, 12))
        assert not df.is_empty()
        assert len(df) == 1
        assert df["symbol"][0] == "SPY"
        assert df["target_index"][0] == "^GSPC"
        assert df["trailing_pe"][0] == 25.5
        assert df["dividend_yield"][0] == 1.2


def test_fetch_extended_endpoints() -> None:
    client = YFinanceClient()
    fetcher = YFinanceDataFetcher(client=client)

    with patch("yfinance.Ticker") as mock_ticker_class:
        mock_ticker_instance = MagicMock()

        # Mock quarterly financials
        mock_fin_df = pd.DataFrame({"2026-06-30": [100.0]}, index=["Total Revenue"])
        mock_ticker_instance.quarterly_financials = mock_fin_df

        # Mock dividends
        mock_div_series = pd.Series([0.25], index=pd.to_datetime(["2026-08-10"]))
        mock_ticker_instance.dividends = mock_div_series

        # Mock analyst target
        mock_ticker_instance.analyst_price_target = {
            "high": 300.0,
            "low": 200.0,
            "mean": 250.0,
            "median": 250.0,
            "current": 240.0,
        }

        # Mock fast info
        mock_fast_info = MagicMock()
        mock_fast_info.last_price = 245.0
        mock_fast_info.previous_close = 240.0
        mock_fast_info.open = 242.0
        mock_fast_info.day_high = 246.0
        mock_fast_info.day_low = 241.0
        mock_fast_info.year_high = 250.0
        mock_fast_info.year_low = 180.0
        mock_fast_info.market_cap = 3000000000000.0
        mock_ticker_instance.fast_info = mock_fast_info

        mock_ticker_class.return_value = mock_ticker_instance

        # Test financials
        fin_df = fetcher.fetch_financials_df("AAPL", statement_type="financials", freq="quarterly")
        assert not fin_df.is_empty()

        # Test dividends
        div_df = fetcher.fetch_actions_df("AAPL", action_type="dividends")
        assert not div_df.is_empty()

        # Test analyst target
        target_df = fetcher.fetch_analyst_target_df("AAPL")
        assert not target_df.is_empty()
        assert target_df["target_high"][0] == 300.0

        # Test fast info
        fast_df = fetcher.fetch_fast_info_df("AAPL")
        assert not fast_df.is_empty()
        assert fast_df["last_price"][0] == 245.0
