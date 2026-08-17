from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_core.exceptions import DataFetchError
from stock_data.fetcher.lixinger.stock_fetcher import LixingerStockFetcher


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


def test_lixinger_stock_fetcher_resolves_short_task_to_api_path() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "stockCode": ["600519"],
            "date": ["2024-01-02T00:00:00"],
            "n_income": [100.0],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    df = fetcher.fetch_daily_bars_df(
        symbol="600519.SH",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        endpoint="fs_non_financial",
    )

    assert not df.is_empty()
    assert mock_client.query.call_args.args[0] == "cn/company/fs/non_financial"


def test_lixinger_stock_fetcher_resolves_l2_task_to_shared_api_path() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "stockCode": ["801010"],
            "date": ["2024-01-02T00:00:00"],
            "pe_ttm.ew": [20.0],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    df = fetcher.fetch_daily_bars_df(
        symbol="801010",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        endpoint="sw_2021_l2_fundamental",
    )

    assert not df.is_empty()
    assert mock_client.query.call_args.args[0] == "cn/industry/fundamental/sw_2021"


def test_lixinger_stock_fetcher_batch_l2_query_uses_level_two_industries() -> None:
    mock_client = MagicMock()

    def query(api_name: str, **kwargs: Any) -> pd.DataFrame:
        if api_name == "cn/industry":
            return pd.DataFrame(
                {
                    "stockCode": ["110000", "801010"],
                    "name": ["农林牧渔", "种植业"],
                    "level": ["one", "two"],
                }
            )
        return pd.DataFrame(
            {
                "stockCode": [kwargs["stockCodes"][0]],
                "date": ["2024-01-02"],
                "pe_ttm.ew": [20.0],
            }
        )

    mock_client.query.side_effect = query
    fetcher = LixingerStockFetcher(client=mock_client)

    with patch("stock_data.fetcher.lixinger.stock_fetcher._INDUSTRY_TABLE_CACHE", None):
        df = fetcher.fetch_daily_bars_df(
            symbol="",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
            endpoint="cn/industry/fundamental/sw_2021",
            endpoint_name="sw_2021_l2_fundamental",
        )

    assert df["stockCode"].to_list() == ["801010"]
    assert mock_client.query.call_args_list[1].kwargs["stockCodes"] == ["801010"]
    assert mock_client.query.call_args_list[1].kwargs["date"] == "2024-01-02"
    assert "endpoint_name" not in mock_client.query.call_args_list[1].kwargs


def test_lixinger_industry_batch_propagates_data_fetch_error() -> None:
    mock_client = MagicMock()

    def query(api_name: str, **kwargs: Any) -> pd.DataFrame:
        if api_name == "cn/industry":
            return pd.DataFrame(
                {
                    "stockCode": ["110000"],
                    "name": ["农林牧渔"],
                    "level": ["one"],
                }
            )
        raise DataFetchError("理杏仁 API 权限不足或额度耗尽 (403)")

    mock_client.query.side_effect = query
    fetcher = LixingerStockFetcher(client=mock_client)

    with (
        patch("stock_data.fetcher.lixinger.stock_fetcher._INDUSTRY_TABLE_CACHE", None),
        pytest.raises(DataFetchError, match="403"),
    ):
        fetcher.fetch_daily_bars_df(
            symbol="",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
            endpoint="sw_2021_fundamental",
        )


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


def test_lixinger_index_candlestick_fills_requested_stock_code() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "date": ["2024-01-02T00:00:00"],
            "open": [3400.0],
            "high": [3420.0],
            "low": [3390.0],
            "close": [3410.0],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    df = fetcher.fetch_daily_bars_df(
        symbol="000300.SH",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        endpoint="index_daily_bar",
    )

    assert df["stockCode"].to_list() == ["000300"]
    assert mock_client.query.call_args.kwargs["stockCode"] == "000300"


def test_lixinger_stock_fetcher_trade_cal() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "date": ["2024-01-02T00:00:00", "2024-01-03T00:00:00"],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)
    with patch("stock_data.update_scheduler.DataUpdateScheduler.get_trading_days", return_value=()):
        dates = fetcher.fetch_trade_cal(date(2024, 1, 1), date(2024, 1, 3))
    assert dates == [date(2024, 1, 2), date(2024, 1, 3)]


def test_lixinger_stock_fetcher_prefers_local_tushare_calendar() -> None:
    mock_client = MagicMock()
    fetcher = LixingerStockFetcher(client=mock_client)

    with patch(
        "stock_data.update_scheduler.DataUpdateScheduler.get_trading_days",
        return_value=(date(2024, 1, 2), date(2024, 1, 3)),
    ):
        dates = fetcher.fetch_trade_cal(date(2024, 1, 1), date(2024, 1, 3))

    assert dates == [date(2024, 1, 2), date(2024, 1, 3)]
    mock_client.query.assert_not_called()


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
