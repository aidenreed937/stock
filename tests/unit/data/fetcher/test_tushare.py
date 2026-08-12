"""TuShare 数据采集模块单元测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import polars as pl
import pytest

from stock.data.fetcher.tushare.client import RateLimiter, TuShareClient
from stock.data.fetcher.tushare.facade import TuShareDataFetcher
from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
from stock.data.fetcher.tushare.slicer import batch_slice_and_merge
from stock.exceptions import DataFetchError


def test_tushare_registry() -> None:
    assert "daily" in TUSHARE_API_REGISTRY
    assert "stock_basic" in TUSHARE_API_REGISTRY
    daily_meta = TUSHARE_API_REGISTRY["daily"]
    assert daily_meta.api_name == "daily"
    assert "ts_code" in daily_meta.primary_keys


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
