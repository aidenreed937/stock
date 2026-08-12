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
