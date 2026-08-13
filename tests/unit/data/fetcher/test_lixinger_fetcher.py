"""理杏仁 (Lixinger) 抓取组件单元测试文件。"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock.config.settings import settings
from stock.data.fetcher.lixinger import (
    LIXINGER_API_REGISTRY,
    LixingerClient,
    LixingerDataFetcher,
    LixingerStockFetcher,
    create_lixinger_pipeline,
)
from stock.data.update_scheduler import DataUpdateScheduler
from stock.exceptions import DataFetchError


def test_lixinger_client_query_success() -> None:
    client = LixingerClient(token="mock_token")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": 0,
        "msg": "success",
        "data": [
            {
                "stockCode": "600519",
                "date": "2026-08-10",
                "pe_ttm": 25.5,
                "pb": 8.2,
                "ps_ttm": 12.1,
                "dyr": 0.023,
                "cp": 1650.0,
            }
        ],
    }

    with patch.object(client._session, "post", return_value=mock_resp):
        df = client.query("cn/company/fundamental/non_financial", stockCodes=["600519"])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert df["stockCode"].iloc[0] == "600519"
        assert df["pe_ttm"].iloc[0] == 25.5


def test_lixinger_client_errors() -> None:
    client = LixingerClient(token="invalid_token")

    mock_401 = MagicMock()
    mock_401.status_code = 401
    mock_401.text = "Unauthorized Token"

    with patch.object(client._session, "post", return_value=mock_401):
        with pytest.raises(DataFetchError, match="Token 验证失效"):
            client.query("cn/company/fundamental/non_financial")


def test_lixinger_client_rejects_range_over_ten_years_before_http() -> None:
    client = LixingerClient(token="mock_token")
    with patch.object(client._session, "post") as post:
        with pytest.raises(DataFetchError, match="超过文档限制 10 年"):
            client.query(
                "cn/index/fundamental",
                stockCodes=["000300"],
                startDate="2010-01-01",
                endDate="2021-01-02",
            )
        post.assert_not_called()


def test_lixinger_client_rejects_invalid_stock_codes_before_http() -> None:
    client = LixingerClient(token="mock_token")
    with patch.object(client._session, "post") as post:
        with pytest.raises(DataFetchError, match="只能传入一个 stockCode"):
            client.query(
                "cn/company/fundamental/non_financial",
                stockCodes=["600519", "000001"],
                startDate="2026-01-01",
                endDate="2026-08-01",
            )
        post.assert_not_called()

    with patch.object(client._session, "post") as post:
        with pytest.raises(DataFetchError, match="数量必须在 1~100"):
            client.query("cn/company/fundamental/non_financial", stockCodes=[])
        post.assert_not_called()

    mock_403 = MagicMock()
    mock_403.status_code = 403
    mock_403.text = "Forbidden"

    with patch.object(client._session, "post", return_value=mock_403):
        with pytest.raises(DataFetchError, match="权限不足"):
            client.query("cn/company/fundamental/non_financial")


def test_lixinger_client_429_retry() -> None:
    client = LixingerClient(token="mock_token", max_retries=2)

    mock_429 = MagicMock()
    mock_429.status_code = 429

    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {"code": 0, "data": [{"stockCode": "600519"}]}

    with patch.object(client._session, "post", side_effect=[mock_429, mock_200]):
        with patch("time.sleep", return_value=None):
            df = client.query("cn/company/fundamental/non_financial")
            assert len(df) == 1


def test_lixinger_stock_fetcher() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        [
            {
                "stockCode": "600519",
                "date": "2026-08-10",
                "pe_ttm": 25.5,
                "open": 1640.0,
                "high": 1660.0,
                "low": 1630.0,
                "close": 1650.0,
                "volume": 10000.0,
                "amount": 1.65e7,
            }
        ]
    )

    fetcher = LixingerStockFetcher(client=mock_client)
    start_d = date(2026, 8, 10)
    end_d = date(2026, 8, 10)

    # 1. fetch_daily_bars_df
    pl_df = fetcher.fetch_daily_bars_df("600519.SH", start_d, end_d)
    assert not pl_df.is_empty()
    assert "pe_ttm" in pl_df.columns

    # 2. fetch_daily_bars
    bars = fetcher.fetch_daily_bars("600519", start_d, end_d)
    assert len(bars) == 1
    assert bars[0].symbol == "600519"
    assert bars[0].close == 1650.0

    # 3. fetch_trade_cal
    mock_client.query.return_value = pd.DataFrame([{"date": "2026-08-10"}])
    trade_dates = fetcher.fetch_trade_cal(start_d, end_d)
    assert trade_dates == [start_d]


def test_lixinger_constituents_are_flattened() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame([
        {"stockCode": "490000", "constituents": [{"stockCode": "600519", "market": "CN"}]}
    ])
    fetcher = LixingerStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        "sw_2021_constituents", date(2026, 8, 1), date(2026, 8, 1), endpoint="cn/industry/constituents/sw_2021"
    )
    assert df.to_dicts() == [{"industryCode": "490000", "stockCode": "600519", "market": "CN"}]


def test_lixinger_facade_and_factory() -> None:
    facade = LixingerDataFetcher(token="test_token")
    assert facade.client.token == "test_token"

    pipeline = create_lixinger_pipeline("company_fundamental")
    assert pipeline.data_source == "lixinger"
    assert pipeline.endpoint == "company_fundamental"


def test_lixinger_update_scheduler() -> None:
    target_date = date(2026, 8, 12)

    # 17:30 (早于 18:00) -> 尚未就绪
    dt_early = datetime(2026, 8, 12, 17, 30)
    assert not DataUpdateScheduler.is_data_ready(
        "cn/company/fundamental/non_financial", target_date, dt_early, data_source="lixinger"
    )

    # 18:30 -> 已就绪
    dt_ready = datetime(2026, 8, 12, 18, 30)
    assert DataUpdateScheduler.is_data_ready(
        "cn/company/fundamental/non_financial", target_date, dt_ready, data_source="lixinger"
    )
