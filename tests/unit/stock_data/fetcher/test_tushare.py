"""TuShare 数据采集模块单元测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import polars as pl
import pytest

from stock_core.exceptions import DataFetchError
from stock_data.fetcher.tushare.client import RateLimiter, TuShareClient
from stock_data.fetcher.tushare.facade import TuShareDataFetcher
from stock_data.fetcher.tushare.factory import create_tushare_pipeline
from stock_data.fetcher.tushare.query_builder import build_tushare_query
from stock_data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
from stock_data.fetcher.tushare.slicer import batch_slice_and_merge
from stock_data.pipeline.cleaner.bar_cleaner import BarDataCleaner


def test_tushare_registry() -> None:
    assert "daily" in TUSHARE_API_REGISTRY
    from stock_data.fetcher.tushare.registry import TUSHARE_TASK_REGISTRY

    assert TUSHARE_TASK_REGISTRY["stock_daily_bar"].api_name == "daily"
    assert "stock_basic" in TUSHARE_API_REGISTRY
    daily_meta = TUSHARE_API_REGISTRY["daily"]
    assert daily_meta.api_name == "daily"
    assert "ts_code" in daily_meta.primary_keys

    stk_limit = TUSHARE_API_REGISTRY["stk_limit"]
    assert stk_limit.primary_keys == ["ts_code", "trade_date"]
    assert stk_limit.units["up_limit"] == "CNY/share"
    assert stk_limit.request_window_days == 1
    assert stk_limit.max_rows_per_request == 5800

    limit_list = TUSHARE_API_REGISTRY["limit_list_d"]
    assert limit_list.primary_keys == ["ts_code", "trade_date", "limit"]
    assert limit_list.required_columns == ["ts_code", "trade_date", "limit"]
    assert limit_list.units["amount"] == "CNY"
    assert limit_list.units["turnover_ratio"] == "percent"
    assert limit_list.max_rows_per_request == 2500


def test_tushare_option_inputs_and_stopped_account_endpoint_are_registered() -> None:
    opt_basic = TUSHARE_API_REGISTRY["opt_basic"]
    assert opt_basic.primary_keys == ["ts_code"]
    assert opt_basic.frequency == "static"

    opt_daily = TUSHARE_API_REGISTRY["opt_daily"]
    assert opt_daily.primary_keys == ["ts_code", "trade_date"]
    assert opt_daily.request_window_days == 1
    assert opt_daily.units["amount"] == "CNY10k"

    stk_account = TUSHARE_API_REGISTRY["stk_account"]
    assert stk_account.frequency == "weekly"
    assert stk_account.required_columns == ["date"]


def test_static_tushare_endpoint_does_not_add_date_filter() -> None:
    meta = TUSHARE_API_REGISTRY["opt_basic"]
    _, query_kwargs = build_tushare_query(
        meta,
        "opt_basic",
        date(2026, 8, 1),
        date(2026, 8, 12),
        {},
    )

    assert query_kwargs == {}


@pytest.mark.parametrize(
    ("endpoint", "start_date", "end_date", "expected"),
    [
        ("cn_cpi", date(2026, 7, 1), date(2026, 7, 1), {"m": "202607"}),
        (
            "cn_cpi",
            date(2026, 6, 1),
            date(2026, 7, 1),
            {"start_m": "202606", "end_m": "202607"},
        ),
        ("cn_gdp", date(2026, 4, 1), date(2026, 6, 30), {"q": "2026Q2"}),
        (
            "cn_gdp",
            date(2026, 1, 1),
            date(2026, 6, 30),
            {"start_q": "2026Q1", "end_q": "2026Q2"},
        ),
        ("shibor", date(2026, 8, 18), date(2026, 8, 18), {"date": "20260818"}),
        (
            "shibor_lpr",
            date(2026, 7, 1),
            date(2026, 7, 1),
            {"start_date": "20260701", "end_date": "20260731"},
        ),
        ("cn_schedule", date(2026, 7, 1), date(2026, 7, 1), {"m": "202607"}),
    ],
)
def test_low_frequency_tushare_query_uses_endpoint_parameters(
    endpoint: str, start_date: date, end_date: date, expected: dict[str, str]
) -> None:
    _, query_kwargs = build_tushare_query(
        TUSHARE_API_REGISTRY[endpoint], endpoint, start_date, end_date, {}
    )

    assert query_kwargs == expected


def test_tushare_factory_uses_bar_cleaner_for_bar_profiles() -> None:
    pipeline = create_tushare_pipeline(endpoint="fund_daily")

    assert isinstance(pipeline.cleaner, BarDataCleaner)


def test_tushare_client_missing_token() -> None:
    client = TuShareClient(token="")
    with pytest.raises(DataFetchError, match="未配置 TuShare API Token"):
        _ = client.pro


def test_rate_limiter_acquire() -> None:
    limiter = RateLimiter(max_requests=5, time_window_seconds=1.0)
    limiter._requests.clear()
    for _ in range(5):
        limiter.acquire()
    assert len(limiter._requests) == 5


def test_batch_slice_and_merge() -> None:
    def mock_fetch_fn(ts_code: str) -> pl.DataFrame:
        codes = ts_code.split(",")
        return pl.DataFrame({"symbol": codes, "value": [10.0] * len(codes)})

    symbols = [f"SYM_{i:03d}" for i in range(120)]
    merged_df = batch_slice_and_merge(mock_fetch_fn, symbols, batch_size=50, max_workers=2)

    assert len(merged_df) == 120
    assert "symbol" in merged_df.columns


@patch("tushare.pro_api")
@patch("tushare.set_token")
def test_tushare_fetcher_with_mock_api(mock_set_token: MagicMock, mock_pro_api: MagicMock) -> None:
    mock_pro = MagicMock()
    mock_pro_api.return_value = mock_pro

    # 模拟 TuShare 返回的 Pandas DataFrame
    mock_pandas_df = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "trade_date": "20260101",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "vol": 1000.0,
                "amount": 10500.0,
            }
        ]
    )
    mock_pro.query.return_value = mock_pandas_df

    fetcher = TuShareDataFetcher(token="mock_token_123")
    df = fetcher.fetch_daily_bars_df("600000.SH", date(2026, 1, 1), date(2026, 1, 2))

    assert not df.is_empty()
    assert "ts_code" in df.columns
    assert df["ts_code"][0] == "600000.SH"


@patch("tushare.pro_api")
@patch("tushare.set_token")
def test_tushare_fetcher_dynamic_endpoint_routing(
    mock_set_token: MagicMock, mock_pro_api: MagicMock
) -> None:
    mock_pro = MagicMock()
    mock_pro_api.return_value = mock_pro
    mock_pro.query.return_value = pd.DataFrame(
        [{"ts_code": "000001.SZ", "pe": 12.5, "trade_date": "20260812"}]
    )

    fetcher = TuShareDataFetcher(token="mock_token_123")

    # 1. 测试全市场单日回填路由 (symbol="", trade_date="20260812")
    df = fetcher.fetch_daily_bars_df(
        "", date(2026, 8, 12), date(2026, 8, 12), endpoint="daily_basic"
    )
    mock_pro.query.assert_called_with("daily_basic", trade_date="20260812")
    assert not df.is_empty()
    assert "pe" in df.columns

    # 2. 测试 index_weight 参数映射 (symbol -> index_code)
    mock_pro.query.return_value = pd.DataFrame(
        [{"index_code": "000300.SH", "con_code": "600519.SH"}]
    )
    df_weight = fetcher.fetch_daily_bars_df(
        "000300.SH", date(2026, 1, 1), date(2026, 8, 12), endpoint="index_weight"
    )
    mock_pro.query.assert_called_with(
        "index_weight", index_code="000300.SH", start_date="20260101", end_date="20260812"
    )
    assert not df_weight.is_empty()


def test_tushare_client_auto_paginates() -> None:
    client = TuShareClient(token="test_token", paginate_threshold=2)
    client._pro_api = MagicMock()
    client._pro_api.query.side_effect = [
        pd.DataFrame({"ts_code": ["A", "B"]}),
        pd.DataFrame({"ts_code": ["C"]}),
    ]
    result = client.query("stock_basic")
    assert result["ts_code"].tolist() == ["A", "B", "C"]


def test_tushare_full_market_does_not_invent_symbol() -> None:
    fetcher = TuShareDataFetcher(token="test_token")
    fetcher.client._pro_api = MagicMock()
    fetcher.client._pro_api.query.return_value = pd.DataFrame(
        {"ts_code": ["000001.SZ"], "trade_date": ["20260812"]}
    )
    df = fetcher.fetch_daily_bars_df("", date(2026, 8, 12), date(2026, 8, 12))
    assert "symbol" not in df.columns


def test_tushare_suspend_d_uses_trade_date_for_full_market_query() -> None:
    fetcher = TuShareDataFetcher(token="test_token")
    fetcher.client._pro_api = MagicMock()
    fetcher.client._pro_api.query.return_value = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260812"],
            "suspend_type": ["S"],
        }
    )

    result = fetcher.fetch_daily_bars_df(
        "", date(2026, 8, 12), date(2026, 8, 12), endpoint="suspend_d"
    )

    fetcher.client._pro_api.query.assert_called_once_with("suspend_d", trade_date="20260812")
    assert result.get_column("trade_date").to_list() == ["20260812"]


def test_tushare_full_market_endpoint_uses_small_request_window() -> None:
    fetcher = TuShareDataFetcher(token="test_token")
    fetcher.client._pro_api = MagicMock()

    def query(api_name: str, **kwargs: str) -> pd.DataFrame:
        assert api_name == "hsgt_top10"
        return pd.DataFrame(
            {
                "ts_code": ["600519.SH"],
                "trade_date": [kwargs["start_date"]],
                "market_type": ["1"],
            }
        )

    fetcher.client._pro_api.query.side_effect = query
    result = fetcher.fetch_daily_bars_df(
        "", date(2026, 1, 1), date(2026, 3, 1), endpoint="hsgt_top10"
    )

    assert len(result) == 2
    calls = fetcher.client._pro_api.query.call_args_list
    assert [(call.kwargs["start_date"], call.kwargs["end_date"]) for call in calls] == [
        ("20260101", "20260130"),
        ("20260131", "20260301"),
    ]


def test_tushare_limit_endpoints_query_by_trade_date() -> None:
    fetcher = TuShareDataFetcher(token="test_token")
    fetcher.client._pro_api = MagicMock()
    fetcher.client._pro_api.query.return_value = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260812"],
            "up_limit": [12.34],
            "down_limit": [10.10],
        }
    )

    fetcher.fetch_daily_bars_df("", date(2026, 8, 12), date(2026, 8, 12), endpoint="stk_limit")
    fetcher.client._pro_api.query.assert_called_once_with("stk_limit", trade_date="20260812")

    fetcher.client._pro_api.query.return_value = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260812"],
            "limit": ["U"],
        }
    )
    fetcher.fetch_daily_bars_df("", date(2026, 8, 12), date(2026, 8, 12), endpoint="limit_list_d")
    fetcher.client._pro_api.query.assert_called_with("limit_list_d", trade_date="20260812")


def test_tushare_drops_internal_endpoint_name_from_upstream_request() -> None:
    fetcher = TuShareDataFetcher(token="test_token")
    fetcher.client._pro_api = MagicMock()
    fetcher.client._pro_api.query.return_value = pd.DataFrame(
        {"month": ["202607"], "m2": [300000.0]}
    )

    result = fetcher.fetch_daily_bars_df(
        "",
        date(2026, 7, 1),
        date(2026, 7, 1),
        endpoint="cn_m",
        endpoint_name="cn_m",
    )

    assert not result.is_empty()
    fetcher.client._pro_api.query.assert_called_once_with("cn_m", m="202607")
