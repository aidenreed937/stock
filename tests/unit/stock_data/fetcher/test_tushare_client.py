from unittest.mock import MagicMock

import pandas as pd
import pytest

from stock_core.exceptions import DataFetchError
from stock_data.fetcher.tushare.client import TuShareClient


def test_tushare_client_missing_token_raises() -> None:
    client = TuShareClient(token="")
    with pytest.raises(DataFetchError, match="未配置 TuShare API Token"):
        _ = client.pro


def test_tushare_client_query_success() -> None:
    client = TuShareClient(token="mock_token")
    mock_pro = MagicMock()
    mock_pro.query.return_value = pd.DataFrame({"ts_code": ["600519.SH"], "close": [1800.0]})
    client._pro_api = mock_pro

    df = client.query("daily", ts_code="600519.SH")
    assert not df.empty
    assert df["ts_code"][0] == "600519.SH"


def test_tushare_client_query_pagination() -> None:
    client = TuShareClient(token="mock_token", paginate_threshold=2)
    mock_pro = MagicMock()
    # 第一页 2 条，第二页 1 条 (< limit 终止)
    mock_pro.query.side_effect = [
        pd.DataFrame({"ts_code": ["A", "B"]}),
        pd.DataFrame({"ts_code": ["C"]}),
    ]
    client._pro_api = mock_pro

    df = client.query("daily", auto_paginate=True)
    assert len(df) == 3
    assert df["ts_code"].to_list() == ["A", "B", "C"]


def test_tushare_client_query_paginates_with_endpoint_limit() -> None:
    client = TuShareClient(token="mock_token")
    mock_pro = MagicMock()
    mock_pro.query.side_effect = [
        pd.DataFrame({"ts_code": ["A", "B"]}),
        pd.DataFrame({"ts_code": ["C"]}),
    ]
    client._pro_api = mock_pro

    df = client.query("stk_surv", pagination_limit=2)

    assert len(df) == 3
    assert mock_pro.query.call_args_list[1].kwargs == {"limit": 2, "offset": 2}


def test_tushare_client_query_rate_limit_retry(monkeypatch) -> None:
    client = TuShareClient(token="mock_token")
    mock_pro = MagicMock()
    mock_pro.query.side_effect = [
        Exception("抱歉，您每分钟最多访问该接口 2 次，ip超限"),
        pd.DataFrame({"ts_code": ["600519.SH"]}),
    ]
    client._pro_api = mock_pro
    monkeypatch.setattr("time.sleep", lambda s: None)

    df = client.query("daily", ts_code="600519.SH")
    assert len(df) == 1


def test_tushare_client_pagination_terminates_on_repeated_page() -> None:
    client = TuShareClient(token="mock_token", paginate_threshold=2)
    mock_pro = MagicMock()
    repeated_page = pd.DataFrame({"ts_code": ["A", "B"]})
    mock_pro.query.side_effect = [repeated_page, repeated_page.copy()]
    client._pro_api = mock_pro

    df = client.query("daily", auto_paginate=True)
    assert len(df) == 2
    assert df["ts_code"].to_list() == ["A", "B"]
