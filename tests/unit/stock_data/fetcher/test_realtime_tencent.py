"""腾讯实时行情适配器测试。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import requests

from stock_core.exceptions import DataFetchError
from stock_data.fetcher.realtime.base import normalize_local_symbol, to_tencent_symbol
from stock_data.fetcher.realtime.tencent import TencentRealtimeFetcher

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class _Response:
    def __init__(self, body: str) -> None:
        self.content = body.encode("gb18030")

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get(self, url: str, *, timeout: float) -> object:
        self.urls.append(f"{url}|timeout={timeout}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _quote_body(code: str = "600519", name: str = "贵州茅台") -> str:
    parts = [
        "1",
        name,
        code,
        "1307.88",
        "1297.99",
        "1300.00",
        "37548",
        "18848",
        "18700",
        "1305.00",
        "20",
        "1303.69",
        "1",
        "1303.00",
        "6",
        "1302.66",
        "1",
        "1302.01",
        "1",
        "1307.88",
        "33",
        "1307.89",
        "1",
        "1307.90",
        "5",
        "1307.94",
        "1",
        "1307.98",
        "1",
        "",
        "20260819155641",
        "9.89",
        "0.76",
        "1308.88",
        "1290.50",
        "1307.88/37548/4876774762",
        "37548",
        "487677",
        "0.30",
    ]
    return "~".join(parts)


def _payload(*rows: tuple[str, str]) -> str:
    return "".join(f'v_{provider}="{body}";' for provider, body in rows)


def test_symbol_mapping_preserves_local_exchange_and_csi_suffix() -> None:
    assert normalize_local_symbol("sh600519") == "600519.SH"
    assert normalize_local_symbol("000001") == "000001.SZ"
    assert to_tencent_symbol("000985.CSI") == "sh000985"
    assert to_tencent_symbol("399001.SZ") == "sz399001"


def test_tencent_fetcher_parses_snapshot_and_normalizes_units() -> None:
    session = _Session(
        [
            _Response(
                _payload(
                    ("sh600519", _quote_body()),
                    ("sh000985", _quote_body("000985", "中证全指")),
                )
            )
        ]
    )
    received_at = datetime(2026, 8, 19, 15, 57, tzinfo=_SHANGHAI_TZ)
    fetcher = TencentRealtimeFetcher(session=session, clock=lambda: received_at)

    quotes = fetcher.fetch_quotes(["600519.SH", "000985.CSI", "000001.SZ"])

    assert [quote.symbol for quote in quotes] == ["600519.SH", "000985.CSI", "000001.SZ"]
    assert quotes[0].status == "valid"
    assert quotes[0].volume == 3_754_800
    assert quotes[0].amount == 4_876_774_762
    assert quotes[0].bid_prices == (1305.0, 1303.69, 1303.0, 1302.66, 1302.01)
    assert quotes[0].quote_at == datetime(2026, 8, 19, 15, 56, 41, tzinfo=_SHANGHAI_TZ)
    assert quotes[2].status == "missing"
    assert "sh600519" in session.urls[0]
    assert "sh000985" in session.urls[0]
    assert "sz000001" in session.urls[0]


def test_tencent_fetcher_retries_request_failure() -> None:
    session = _Session(
        [requests.ConnectionError("temporary"), _Response(_payload(("sh600519", _quote_body())))]
    )
    fetcher = TencentRealtimeFetcher(
        session=session,
        max_retries=1,
        retry_backoff_seconds=0,
    )

    quotes = fetcher.fetch_quotes(["600519.SH"])

    assert quotes[0].is_valid
    assert len(session.urls) == 2


def test_tencent_fetcher_raises_when_response_has_no_rows() -> None:
    fetcher = TencentRealtimeFetcher(session=_Session([_Response('v_pv_none="";')]), max_retries=0)

    with pytest.raises(DataFetchError, match="腾讯实时行情请求失败"):
        fetcher.fetch_quotes(["600519.SH"])
