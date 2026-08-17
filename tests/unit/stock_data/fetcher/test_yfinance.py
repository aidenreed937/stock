from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import polars as pl

from stock_data.fetcher.yfinance.client import YFinanceClient
from stock_data.fetcher.yfinance.factory import create_yfinance_pipeline
from stock_data.fetcher.yfinance.global_fetcher import YFinanceDataFetcher
from stock_data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY
from stock_data.pipeline.cleaner.macro_cleaner import MacroDataCleaner


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


def test_yfinance_retry_keeps_proxy_aware_session() -> None:
    client = YFinanceClient(proxy="http://mock-proxy")
    first_session = MagicMock(name="first_session")
    retry_session = MagicMock(name="retry_session")
    first_ticker = MagicMock(name="first_ticker")
    retry_ticker = MagicMock(name="retry_ticker")
    retry_ticker.history.return_value = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1000.0],
        },
        index=pd.to_datetime(["2026-01-02"]),
    )
    first_ticker.history.side_effect = RuntimeError("proxy request failed")

    with (
        patch.object(client, "_get_session", side_effect=[first_session, retry_session]),
        patch.object(client.rate_limiter, "acquire") as acquire,
        patch("stock_data.fetcher.yfinance.client.time.sleep") as sleep,
        patch("stock_data.fetcher.yfinance.client.random.uniform", return_value=0.0),
        patch("yfinance.Ticker", side_effect=[first_ticker, retry_ticker]) as ticker_cls,
    ):
        result = client.query_history("^GSPC", "2026-01-01", "2026-01-03")

    assert not result.empty
    assert acquire.call_count == 2
    sleep.assert_called_once_with(client.RETRY_DELAY_SECONDS)
    assert ticker_cls.call_args_list[0].kwargs["session"] is first_session
    assert ticker_cls.call_args_list[1].kwargs["session"] is retry_session


def test_yfinance_proxy_pool_rotates_on_retry(tmp_path) -> None:
    pool_file = tmp_path / "yfinance.txt"
    pool_file.write_text(
        "http://proxy-a\n# disabled\nhttp://proxy-b\nhttp://proxy-a\n",
        encoding="utf-8",
    )
    client = YFinanceClient(proxy_pool_file=pool_file)
    client._proxy_index = 0
    first_ticker = MagicMock(name="first_ticker")
    retry_ticker = MagicMock(name="retry_ticker")
    retry_ticker.history.return_value = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1000.0],
        },
        index=pd.to_datetime(["2026-01-02"]),
    )
    first_ticker.history.side_effect = RuntimeError("proxy request failed")
    selected_proxies: list[str | None] = []

    def fake_get_session(proxy: str | None = None) -> MagicMock:
        selected_proxies.append(proxy)
        return MagicMock()

    with (
        patch.object(client, "_get_session", side_effect=fake_get_session),
        patch.object(client.rate_limiter, "acquire"),
        patch("stock_data.fetcher.yfinance.client.time.sleep"),
        patch("stock_data.fetcher.yfinance.client.random.uniform", return_value=0.0),
        patch("yfinance.Ticker", side_effect=[first_ticker, retry_ticker]),
    ):
        result = client.query_history("^GSPC", "2026-01-01", "2026-01-03")

    assert not result.empty
    assert client.proxy_pool == ("http://proxy-a", "http://proxy-b")
    assert selected_proxies == ["http://proxy-a", "http://proxy-b"]


def test_yfinance_rate_limit_uses_exponential_backoff_and_more_proxies(tmp_path) -> None:
    pool_file = tmp_path / "yfinance.txt"
    pool_file.write_text(
        "http://proxy-a\nhttp://proxy-b\nhttp://proxy-c\n",
        encoding="utf-8",
    )
    client = YFinanceClient(proxy_pool_file=pool_file)
    client._proxy_index = 0

    tickers = [MagicMock(name=f"ticker-{index}") for index in range(3)]
    tickers[0].history.side_effect = RuntimeError("Too Many Requests. Rate limited.")
    tickers[1].history.side_effect = RuntimeError("Too Many Requests. Rate limited.")
    tickers[2].history.return_value = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1.0],
        },
        index=pd.to_datetime(["2026-01-02"]),
    )

    with (
        patch.object(client, "_get_session", return_value=MagicMock()),
        patch.object(client.rate_limiter, "acquire"),
        patch("stock_data.fetcher.yfinance.client.time.sleep") as sleep,
        patch("stock_data.fetcher.yfinance.client.random.uniform", return_value=0.0),
        patch("yfinance.Ticker", side_effect=tickers),
    ):
        result = client.query_history("^GSPC", "2026-01-01", "2026-01-03")

    assert not result.empty
    assert sleep.call_args_list == [
        ((client.RATE_LIMIT_RETRY_DELAY_SECONDS,), {}),
        ((client.RATE_LIMIT_RETRY_DELAY_SECONDS * 2,), {}),
    ]
    assert client._proxy_unavailable_until.keys() == {
        "http://proxy-a",
        "http://proxy-b",
    }


def test_yfinance_proxy_pool_loads_txt_files_from_directory(tmp_path) -> None:
    pool_dir = tmp_path / "proxy"
    pool_dir.mkdir()
    (pool_dir / "100个节点.txt").write_text(
        "user:password@proxy-a:3129\nhttp://proxy-b:8080\n",
        encoding="utf-8",
    )

    client = YFinanceClient(proxy_pool_file=pool_dir)

    assert client.proxy_pool == (
        "http://user:password@proxy-a:3129",
        "http://proxy-b:8080",
    )


def test_create_yfinance_pipeline() -> None:
    pipeline = create_yfinance_pipeline(proxy="http://some-proxy")
    assert pipeline.data_source == "yfinance"
    assert pipeline.endpoint == "stock_daily_bar"
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

        df = fetcher.fetch_index_valuations_df(
            etf_map={"SPY": "^GSPC"}, target_date=date(2026, 8, 12)
        )
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


def test_fetch_macro_indicators() -> None:
    client = YFinanceClient()
    fetcher = YFinanceDataFetcher(client=client)

    mock_df = pd.DataFrame(
        {
            "Open": [4.5],
            "High": [4.6],
            "Low": [4.4],
            "Close": [4.55],
            "Volume": [0.0],
        },
        index=pd.to_datetime(["2026-08-10"]),
    )

    with patch("yfinance.Ticker") as mock_ticker_class:
        mock_ticker_instance = MagicMock()
        mock_ticker_instance.history.return_value = mock_df
        mock_ticker_class.return_value = mock_ticker_instance

        macro_df = fetcher.fetch_macro_indicators_df(
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 11),
            symbols=["^TNX"],
        )
        assert not macro_df.is_empty()
        assert len(macro_df) == 1
        assert macro_df["symbol"][0] == "^TNX"
        mock_ticker_instance.history.assert_called_once_with(
            start="2026-08-10",
            end="2026-08-12",
            interval="1d",
            auto_adjust=False,
            repair=True,
        )


def test_fetch_macro_indicators_preserves_signed_values() -> None:
    client = MagicMock(spec=YFinanceClient)
    client.query_history.return_value = pd.DataFrame(
        {
            "Open": [-0.012],
            "High": [-0.010],
            "Low": [-0.013],
            "Close": [-0.011],
            "Volume": [0.0],
        },
        index=pd.to_datetime(["2026-08-10"]),
    )
    fetcher = YFinanceDataFetcher(client=client)

    macro_df = fetcher.fetch_macro_indicators_df(
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 11),
        symbols=["^IRX"],
    )

    assert macro_df["close"][0] == -0.011
    assert macro_df["amount"][0] == 0.0
    client.query_history.assert_called_once_with(
        symbol="^IRX",
        start_date_str="2026-08-10",
        end_date_str="2026-08-12",
        auto_adjust=False,
        repair=True,
    )


def test_create_yfinance_macro_pipeline_uses_macro_cleaner() -> None:
    pipeline = create_yfinance_pipeline(endpoint="macro_indicators")

    assert isinstance(pipeline.cleaner, MacroDataCleaner)


def test_fetch_daily_bars_df_dispatches_macro_indicators() -> None:
    client = YFinanceClient()
    fetcher = YFinanceDataFetcher(client=client)
    sentinel = MagicMock()

    with patch.object(
        fetcher,
        "fetch_macro_indicators_df",
        return_value=sentinel,
    ) as mock_macro:
        result = fetcher.fetch_daily_bars_df(
            "macro_indicators",
            date(2026, 8, 10),
            date(2026, 8, 11),
            endpoint="macro_indicators",
        )

    assert result is sentinel
    mock_macro.assert_called_once_with(
        date(2026, 8, 10),
        date(2026, 8, 11),
        symbols=None,
    )


def test_yfinance_macro_registry_declares_global_hg_f_route() -> None:
    meta = YFINANCE_API_REGISTRY["macro_indicators"]
    assert meta.market == "GLOBAL"
    assert meta.group == "macro_data"

    fetcher = YFinanceDataFetcher(client=YFinanceClient())
    with patch(
        "stock_data.fetcher.yfinance.macro_fetcher.fetch_macro_daily_bars_df",
        return_value=pl.DataFrame(),
    ) as macro:
        fetcher.fetch_macro_indicators_df(date(2026, 8, 10), date(2026, 8, 11))

    symbols = [call.args[1] for call in macro.call_args_list]
    assert "CNH=X" not in symbols
    assert "GC=F" in symbols
    assert "CL=F" in symbols
    assert "HG=F" in symbols


def test_yfinance_fetcher_trade_cal() -> None:
    client = YFinanceClient()
    fetcher = YFinanceDataFetcher(client=client)
    dates = fetcher.fetch_trade_cal(date(2024, 1, 5), date(2024, 1, 8))
    # 2024-01-05 (Fri), 2024-01-08 (Mon)
    assert dates == [date(2024, 1, 5), date(2024, 1, 8)]


def test_yfinance_fetcher_index_valuations() -> None:
    client = YFinanceClient()
    fetcher = YFinanceDataFetcher(client=client)

    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_instance = MagicMock()
        mock_instance.info = {
            "trailingPE": 25.5,
            "forwardPE": 22.0,
            "priceToBook": 4.5,
            "priceToSalesTrailing12Months": 3.0,
            "yield": 0.015,
            "totalAssets": 5e11,
        }
        mock_ticker_cls.return_value = mock_instance

        df = fetcher.fetch_index_valuations_df(
            etf_map={"SPY": "^GSPC"}, target_date=date(2024, 1, 2)
        )
        assert not df.is_empty()
        assert df["symbol"][0] == "SPY"
        assert df["target_index"][0] == "^GSPC"
        assert df["trailing_pe"][0] == 25.5


def test_yfinance_fetcher_financials_and_actions() -> None:
    import pandas as pd

    client = YFinanceClient()
    fetcher = YFinanceDataFetcher(client=client)

    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_instance = MagicMock()
        mock_instance.quarterly_financials = pd.DataFrame(
            {"2024-01-01": [100.0, 50.0]}, index=["Total Revenue", "Net Income"]
        )
        mock_instance.dividends = pd.Series(
            [0.5, 0.6],
            index=[pd.Timestamp("2024-01-01"), pd.Timestamp("2024-04-01")],
        )
        mock_ticker_cls.return_value = mock_instance

        df_fin = fetcher.fetch_financials_df("AAPL", statement_type="financials", freq="quarterly")
        assert not df_fin.is_empty()
        assert df_fin["symbol"][0] == "AAPL"

        df_act = fetcher.fetch_actions_df("AAPL", action_type="dividends")
        assert not df_act.is_empty()
        assert df_act["symbol"][0] == "AAPL"
