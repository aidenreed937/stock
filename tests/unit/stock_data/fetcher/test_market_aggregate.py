"""东方财富全市场聚合行情适配器测试。"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import requests

from stock_core.exceptions import DataFetchError
from stock_data.fetcher.realtime.market_aggregate import MarketAggregateFetcher

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class _Session:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.params: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params: dict[str, object],
        timeout: float,
        headers: dict[str, str],
    ) -> _Response:
        del url, timeout, headers
        self.params.append(params)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, _Response)
        return response


def _row(
    code: str,
    change: float,
    amount: float,
    market_value: float,
    free_float_value: float,
) -> dict[str, object]:
    return {
        "f2": 10.0,
        "f3": change,
        "f5": 100.0,
        "f6": amount,
        "f8": 1.0,
        "f12": code,
        "f13": 0,
        "f14": code,
        "f18": 10.0,
        "f20": market_value,
        "f21": free_float_value,
    }


def _payload(total: int, *rows: dict[str, object]) -> dict[str, Any]:
    return {"rc": 0, "data": {"total": total, "diff": list(rows)}}


def test_fetcher_aggregates_multiple_pages_without_exposing_rows() -> None:
    rows = [
        _row("000001", 10.0, 100.0, 1000.0, 500.0),
        _row("000002", -5.0, 300.0, 2000.0, 1000.0),
        _row("000003", 0.0, 50.0, 3000.0, 1500.0),
        _row("000004", 2.0, 50.0, 4000.0, 2000.0),
    ]
    session = _Session(
        [
            _Response(_payload(4, *rows[:3])),
            _Response(_payload(4, rows[3])),
        ]
    )
    received_at = datetime(2026, 8, 19, 10, 0, tzinfo=_SHANGHAI_TZ)
    fetcher = MarketAggregateFetcher(
        session=session,
        page_size=3,
        clock=lambda: received_at,
    )

    snapshot = fetcher.fetch_aggregate()

    assert snapshot.status == "valid"
    assert snapshot.reported_count == 4
    assert snapshot.returned_count == 4
    assert snapshot.coverage_ratio == 1.0
    assert snapshot.priced_count == 4
    assert snapshot.change_count == 4
    assert snapshot.advance_count == 2
    assert snapshot.decline_count == 1
    assert snapshot.flat_count == 1
    assert snapshot.advance_share == pytest.approx(0.5)
    assert snapshot.decline_share == pytest.approx(0.25)
    assert snapshot.advance_decline_ratio == pytest.approx(2.0)
    assert snapshot.strong_up_count == 1
    assert snapshot.strong_down_count == 1
    assert snapshot.median_pct_change == pytest.approx(1.0)
    assert snapshot.pct_change_p25 == pytest.approx(-1.25)
    assert snapshot.pct_change_p75 == pytest.approx(4.0)
    assert snapshot.weighted_pct_change == pytest.approx(-0.8)
    assert snapshot.amount_total_yuan == pytest.approx(500.0)
    assert snapshot.total_market_value_yuan == pytest.approx(10000.0)
    assert snapshot.free_float_market_value_yuan == pytest.approx(5000.0)
    assert snapshot.free_float_turnover_pct == pytest.approx(10.0)
    assert snapshot.amount_top_5pct_share == pytest.approx(0.6)
    assert [params["pn"] for params in session.params] == [1, 2]


def test_fetcher_marks_partial_coverage_when_page_limit_or_response_is_incomplete() -> None:
    session = _Session(
        [
            _Response(
                _payload(
                    5,
                    _row("000001", 1.0, 10.0, 100.0, 50.0),
                    _row("000002", -1.0, 10.0, 100.0, 50.0),
                )
            ),
            _Response(_payload(5, _row("000003", 0.0, 10.0, 100.0, 50.0))),
        ]
    )
    fetcher = MarketAggregateFetcher(session=session, page_size=2)

    snapshot = fetcher.fetch_aggregate()

    assert snapshot.status == "partial"
    assert snapshot.returned_count == 3
    assert snapshot.reported_count == 5
    assert snapshot.coverage_ratio == pytest.approx(0.6)
    assert len(session.params) == 2


def test_fetcher_retries_transient_request_failure() -> None:
    session = _Session(
        [
            requests.ConnectionError("temporary"),
            _Response(_payload(1, _row("000001", 1.0, 10.0, 100.0, 50.0))),
        ]
    )
    fetcher = MarketAggregateFetcher(session=session, max_retries=1, retry_backoff_seconds=0)

    snapshot = fetcher.fetch_aggregate()

    assert snapshot.is_usable
    assert len(session.params) == 2


def test_fetcher_raises_after_all_request_attempts_fail() -> None:
    session = _Session(
        [
            requests.ConnectionError("temporary"),
            requests.Timeout("timeout"),
        ]
    )
    fetcher = MarketAggregateFetcher(session=session, max_retries=1, retry_backoff_seconds=0)

    with pytest.raises(DataFetchError, match="attempts=2"):
        fetcher.fetch_aggregate()


def test_fetcher_rejects_empty_market_response() -> None:
    fetcher = MarketAggregateFetcher(
        session=_Session([_Response(_payload(0))]),
        max_retries=0,
    )

    with pytest.raises(DataFetchError, match="未返回 A 股标的"):
        fetcher.fetch_aggregate()
