"""理杏仁 (Lixinger) 抓取组件单元测试文件。"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_core.exceptions import DataFetchError
from stock_data.fetcher.lixinger import (
    LixingerClient,
    LixingerDataFetcher,
    LixingerStockFetcher,
    create_lixinger_pipeline,
)
from stock_data.fetcher.lixinger.client import _SHARED_LIMITERS
from stock_data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY
from stock_data.pipeline.scheduler import DataUpdateScheduler


def test_lixinger_clients_share_one_global_rate_limiter() -> None:
    _SHARED_LIMITERS.clear()
    first = LixingerClient(token="mock_token", rate_limit_per_min=7)
    second = LixingerClient(token="mock_token", rate_limit_per_min=7)

    assert first._get_rate_limiter("first/api") is second._get_rate_limiter("second/api")
    assert len(_SHARED_LIMITERS) == 1


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


def test_lixinger_client_requires_token() -> None:
    client = LixingerClient(token="")

    with pytest.raises(DataFetchError, match="未配置理杏仁 API Token"):
        client.query("cn/index/fundamental")


def test_lixinger_pledge_contract_uses_last_data_date() -> None:
    meta = LIXINGER_API_REGISTRY["cn/company/hot/ple"]

    assert meta.primary_keys == ["stockCode"]
    assert meta.required_columns == ["stockCode", "last_data_date"]
    assert meta.date_columns == ["last_data_date"]


@pytest.mark.parametrize(
    "api_name",
    [
        "cn/company/measures",
        "cn/company/inquiry",
    ],
)
def test_lixinger_risk_event_contracts(api_name: str) -> None:
    meta = LIXINGER_API_REGISTRY[api_name]

    assert meta.primary_keys == ["stockCode", "date", "type", "linkUrl"]
    assert meta.required_columns == ["stockCode", "date", "type"]
    assert meta.date_columns == ["date"]
    assert meta.frequency == "event"
    assert meta.nullable_primary_keys == ["linkUrl"]


@pytest.mark.parametrize("endpoint", ["regulatory_measures", "exchange_inquiry"])
def test_lixinger_risk_event_response_fills_requested_stock_code(endpoint: str) -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "date": ["2026-08-19"],
            "type": ["sw"],
            "linkUrl": [None],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    frame = fetcher.fetch_daily_bars_df(
        "600519",
        date(2026, 8, 1),
        date(2026, 8, 20),
        endpoint=endpoint,
    )

    assert frame["stockCode"].to_list() == ["600519"]
    assert mock_client.query.call_args.kwargs["stockCode"] == "600519"


def test_lixinger_pledge_without_source_date_adds_nullable_date_column() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "stockCode": ["002270"],
            "ps": [0],
            "ps_mc": [0],
            "ps_shbt10sh_r": [0.0],
            "ps_sc_r": [0.0],
            "pc": [0],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    frame = fetcher.fetch_daily_bars_df(
        "002270", date(2026, 8, 15), date(2026, 8, 19), endpoint="pledge_info"
    )

    assert "last_data_date" in frame.columns
    assert frame["last_data_date"].to_list() == [None]


def test_lixinger_unlock_summary_batches_stock_codes_and_fills_missing_date() -> None:
    mock_client = MagicMock()
    codes = [f"{index:06d}" for index in range(101)]
    mock_client.query.side_effect = [
        pd.DataFrame({"stockCode": codes[:100], "srl_last": [1.0] * 100}),
        pd.DataFrame({"stockCode": codes[100:], "srl_last": [2.0]}),
    ]
    fetcher = LixingerStockFetcher(client=mock_client)

    frame = fetcher.fetch_daily_bars_df(
        "unlock_summary",
        date(2026, 8, 1),
        date(2026, 8, 20),
        endpoint="unlock_summary",
        stockCodes=codes,
    )

    assert len(frame) == 101
    assert "last_data_date" in frame.columns
    assert all(len(call.kwargs["stockCodes"]) <= 100 for call in mock_client.query.call_args_list)
    assert len(mock_client.query.call_args_list) == 2


def test_lixinger_unlock_summary_paginates_until_empty_page() -> None:
    mock_client = MagicMock()
    mock_client.query.side_effect = [
        pd.DataFrame({"stockCode": ["600519", "000001"]}),
        pd.DataFrame(),
    ]
    fetcher = LixingerStockFetcher(client=mock_client)

    frame = fetcher.fetch_daily_bars_df(
        "unlock_summary",
        date(2026, 8, 1),
        date(2026, 8, 20),
        endpoint="unlock_summary",
        pageSize=2,
    )

    assert len(frame) == 2
    assert mock_client.query.call_count == 2
    assert mock_client.query.call_args_list[0].kwargs["pageIndex"] == 0
    assert mock_client.query.call_args_list[1].kwargs["pageIndex"] == 1
    assert "last_data_date" in frame.columns


def test_lixinger_daily_macro_query_pads_exclusive_date_range() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "date": ["2026-08-18"],
            "areaCode": ["cn"],
            "tcm_y10": [0.017],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    fetcher.fetch_daily_bars_df("", date(2026, 8, 18), date(2026, 8, 19), endpoint="national_debt")

    kwargs = mock_client.query.call_args.kwargs
    assert kwargs["startDate"] == "2026-08-17"
    assert kwargs["endDate"] == "2026-08-20"


def test_lixinger_financial_contracts_exclude_probe_invalid_metrics() -> None:
    assert "q.fi.roe.t" not in LIXINGER_API_REGISTRY["cn/company/fs/non_financial"].default_metrics
    assert "q.bs.pcr.t" not in LIXINGER_API_REGISTRY["cn/company/fs/bank"].default_metrics
    assert "q.ps.bni.t" not in LIXINGER_API_REGISTRY["cn/company/fs/security"].default_metrics
    assert "q.ps.ibni.t" not in LIXINGER_API_REGISTRY["cn/company/fs/security"].default_metrics
    assert "q.fi.roe.t" not in LIXINGER_API_REGISTRY["cn/company/fs/security"].default_metrics
    assert "q.fi.roe.t" not in LIXINGER_API_REGISTRY["cn/company/fs/insurance"].default_metrics


def test_lixinger_client_query_batch_uses_one_request_for_date_query() -> None:
    client = LixingerClient(token="mock_token")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": 0,
        "data": [
            {"stockCode": "000001", "date": "2026-08-14"},
            {"stockCode": "000300", "date": "2026-08-14"},
        ],
    }

    with patch.object(client._session, "post", return_value=mock_resp) as post:
        df = client.query_batch(
            "cn/index/fundamental",
            ["000001", "000300"],
            date="2026-08-14",
        )

    assert len(df) == 2
    assert post.call_count == 1
    assert post.call_args.kwargs["json"]["stockCodes"] == ["000001", "000300"]


def test_lixinger_client_query_batch_splits_at_one_hundred_codes() -> None:
    client = LixingerClient(token="mock_token")
    codes = [f"{index:06d}" for index in range(101)]
    frames = [
        pd.DataFrame({"stockCode": codes[:100]}),
        pd.DataFrame({"stockCode": codes[100:]}),
    ]

    with patch.object(client, "query", side_effect=frames) as query:
        df = client.query_batch("cn/index/fundamental", codes, date="2026-08-14")

    assert len(df) == 101
    assert query.call_count == 2
    assert len(query.call_args_list[0].kwargs["stockCodes"]) == 100
    assert query.call_args_list[1].kwargs["stockCodes"] == [codes[100]]


def test_lixinger_client_query_batch_falls_back_to_single_codes_for_history() -> None:
    client = LixingerClient(token="mock_token")
    with patch.object(
        client,
        "query",
        return_value=pd.DataFrame({"stockCode": ["000001"]}),
    ) as query:
        client.query_batch(
            "cn/index/fundamental",
            ["000001", "000300"],
            startDate="2026-01-01",
            endDate="2026-08-14",
        )

    assert [call.kwargs["stockCodes"] for call in query.call_args_list] == [
        ["000001"],
        ["000300"],
    ]


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
    mock_429.headers = {"Retry-After": "3"}

    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {"code": 0, "data": [{"stockCode": "600519"}]}

    with patch.object(client._session, "post", side_effect=[mock_429, mock_200]):
        with patch("time.sleep", return_value=None) as sleep:
            df = client.query("cn/company/fundamental/non_financial")
            assert len(df) == 1
    sleep.assert_called_once_with(3.0)


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


def test_lixinger_index_fundamental_uses_batch_stock_codes() -> None:
    mock_client = MagicMock()
    mock_client.query_batch.return_value = pd.DataFrame(
        {
            "stockCode": ["000001", "000300"],
            "date": ["2026-08-10", "2026-08-10"],
            "pe_ttm.ew": [10.0, 12.0],
        }
    )
    config = SimpleNamespace(
        watchlists=SimpleNamespace(
            lixinger=SimpleNamespace(indices=["000001", "000300", "399102"])
        ),
        source_endpoint_supports={"lixinger": {"index_fundamental": ["000001", "000300"]}},
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    with patch(
        "stock_data.fetcher.lixinger.stock_fetcher.load_data_config",
        return_value=config,
    ):
        df = fetcher.fetch_daily_bars_df(
            symbol="",
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 10),
            endpoint="index_fundamental",
        )

    assert len(df) == 2
    mock_client.query_batch.assert_called_once()
    args, kwargs = mock_client.query_batch.call_args
    assert args[:2] == ("cn/index/fundamental", ["000001", "000300"])
    assert kwargs["date"] == "2026-08-10"
    assert "startDate" not in kwargs
    assert "endDate" not in kwargs
    assert kwargs["metricsList"] == [
        "pe_ttm.ew",
        "pe_ttm.mcw",
        "pb.ew",
        "pb.mcw",
        "ps_ttm.ew",
        "ps_ttm.mcw",
        "dyr.ew",
        "dyr.mcw",
        "mc",
    ]


def test_lixinger_investor_accounts_use_macro_investor_route() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        {
            "date": ["2026-08-10"],
            "nni_m": [12.0],
            "n_non_ni_m": [0.4],
        }
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    result = fetcher.fetch_daily_bars_df(
        symbol="",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 10),
        endpoint="investor_accounts",
    )

    assert result.get_column("nni_m").to_list() == [12.0]
    mock_client.query.assert_called_once_with(
        "macro/investor",
        areaCode="cn",
        metricsList=["ni", "non_ni", "nni_m", "n_non_ni_m"],
        startDate="2026-08-01",
        endDate="2026-08-10",
    )


def test_lixinger_money_supply_flattens_nested_values_and_units() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        [
            {
                "date": "2026-06-29T16:00:00.000Z",
                "m": {
                    "m0": {"t": 14500000000000, "t_y2y": 0.02},
                    "m1": {"t": 114000000000000, "t_y2y": -0.01},
                    "m2": {"t": 350000000000000, "t_y2y": 0.08},
                },
            },
            {
                "date": "2026-07-30T16:00:00.000Z",
                "m": {
                    "m0": {"t": 14800000000000, "t_y2y": 0.03},
                    "m1": {"t": 115000000000000, "t_y2y": 0.01},
                    "m2": {"t": 355000000000000, "t_y2y": 0.07},
                },
            },
        ]
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    frame = fetcher.fetch_daily_bars_df("", date(2026, 6, 1), date(2026, 8, 17), endpoint="cn_m")

    assert frame["month"].to_list() == ["202606", "202607"]
    assert frame["m1"].to_list() == [1_140_000.0, 1_150_000.0]
    assert frame["m1_yoy"].to_list() == [-1.0, 1.0]
    assert frame["m1_mom"].to_list() == [None, pytest.approx(0.87719298)]
    mock_client.query.assert_called_once_with(
        "macro/money-supply",
        areaCode="cn",
        metricsList=[
            "m.m0.t",
            "m.m0.t_y2y",
            "m.m1.t",
            "m.m1.t_y2y",
            "m.m2.t",
            "m.m2.t_y2y",
        ],
        startDate="2026-06-01",
        endDate="2026-08-17",
    )


def test_lixinger_social_financing_flattens_stock_and_yoy() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        [
            {
                "date": "2026-07-30T16:00:00.000Z",
                "m": {"sf": {"t": 463270000000000, "t_y2y": 0.074}},
            }
        ]
    )
    fetcher = LixingerStockFetcher(client=mock_client)

    frame = fetcher.fetch_daily_bars_df(
        "", date(2026, 7, 1), date(2026, 8, 17), endpoint="sf_month"
    )

    row = frame.to_dicts()[0]
    assert row["symbol"] == "sf_month"
    assert row["month"] == "202607"
    assert row["stk_endval"] == pytest.approx(4_632_700.0)
    assert row["stk_endval_yoy"] == pytest.approx(7.4)


def test_lixinger_constituents_are_flattened() -> None:
    mock_client = MagicMock()
    mock_client.query.return_value = pd.DataFrame(
        [{"stockCode": "490000", "constituents": [{"stockCode": "600519", "market": "CN"}]}]
    )
    fetcher = LixingerStockFetcher(client=mock_client)
    df = fetcher.fetch_daily_bars_df(
        "sw_2021_constituents",
        date(2026, 8, 1),
        date(2026, 8, 1),
        endpoint="cn/industry/constituents/sw_2021",
    )
    assert df.to_dicts() == [{"industryCode": "490000", "stockCode": "600519", "market": "CN"}]


def test_lixinger_facade_and_factory() -> None:
    facade = LixingerDataFetcher(token="test_token")
    assert facade.client.token == "test_token"

    pipeline = create_lixinger_pipeline("company_fundamental")
    assert pipeline.data_source == "lixinger"
    assert pipeline.endpoint == "company_fundamental"


def test_lixinger_index_fundamental_factory_uses_placeholder_cleaner() -> None:
    from stock_data.pipeline.cleaner.generic_cleaner import LixingerIndexFundamentalCleaner

    pipeline = create_lixinger_pipeline("index_fundamental")

    assert isinstance(pipeline.cleaner, LixingerIndexFundamentalCleaner)


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
