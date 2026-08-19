"""腾讯批量快照全市场聚合适配器测试。"""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stock_core.exceptions import DataFetchError
from stock_data.fetcher.realtime.base import BaseRealtimeFetcher, RealtimeQuote, to_tencent_symbol
from stock_data.fetcher.realtime.market_aggregate import TencentMarketAggregateFetcher

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class _QuoteFetcher(BaseRealtimeFetcher):
    source = "tencent"

    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.batches: list[tuple[str, ...]] = []

    def fetch_quotes(self, symbols: Sequence[str]) -> tuple[RealtimeQuote, ...]:
        self.batches.append(tuple(symbols))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, tuple)
        return response


def _quote(
    symbol: str,
    price: float,
    pre_close: float,
    amount: float,
    market_value: float,
    free_float_value: float,
    *,
    quote_at: datetime | None = None,
) -> RealtimeQuote:
    received_at = datetime(2026, 8, 19, 10, 0, tzinfo=_SHANGHAI_TZ)
    return RealtimeQuote(
        symbol=symbol,
        provider_symbol=to_tencent_symbol(symbol),
        received_at=received_at,
        quote_at=quote_at,
        price=price,
        pre_close=pre_close,
        amount=amount,
        total_market_value_yuan=market_value,
        free_float_market_value_yuan=free_float_value,
    )


def test_fetcher_aggregates_tencent_batches_without_exposing_rows() -> None:
    quote_at = datetime(2026, 8, 19, 10, 0, 3, tzinfo=_SHANGHAI_TZ)
    quotes = (
        _quote("000001.SZ", 11.0, 10.0, 100.0, 1000.0, 500.0, quote_at=quote_at),
        _quote("000002.SZ", 9.5, 10.0, 300.0, 2000.0, 1000.0, quote_at=quote_at),
        _quote("000003.SZ", 10.0, 10.0, 50.0, 3000.0, 1500.0, quote_at=quote_at),
        _quote("000004.SZ", 10.2, 10.0, 50.0, 4000.0, 2000.0, quote_at=quote_at),
    )
    quote_fetcher = _QuoteFetcher([quotes[:2], quotes[2:]])
    received_at = datetime(2026, 8, 19, 10, 0, tzinfo=_SHANGHAI_TZ)
    fetcher = TencentMarketAggregateFetcher(
        symbols=["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
        quote_fetcher=quote_fetcher,
        batch_size=2,
        clock=lambda: received_at,
    )

    snapshot = fetcher.fetch_aggregate()

    assert snapshot.source == "tencent"
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
    assert quote_fetcher.batches == [
        ("000001.SZ", "000002.SZ"),
        ("000003.SZ", "000004.SZ"),
    ]


def test_fetcher_normalizes_symbols_and_marks_missing_quotes_partial() -> None:
    quotes = (
        _quote("000001.SZ", 11.0, 10.0, 100.0, 1000.0, 500.0),
        _quote("600519.SH", 100.0, 100.0, 300.0, 2000.0, 1000.0),
    )
    quote_fetcher = _QuoteFetcher([quotes])
    fetcher = TencentMarketAggregateFetcher(
        symbols=["000001", "sh600519", "000001.SZ"],
        quote_fetcher=quote_fetcher,
        batch_size=10,
    )

    snapshot = fetcher.fetch_aggregate()

    assert snapshot.status == "valid"
    assert snapshot.reported_count == 2
    assert snapshot.returned_count == 2
    assert quote_fetcher.batches == [("000001.SZ", "600519.SH")]


def test_fetcher_continues_after_one_batch_failure_and_marks_partial() -> None:
    quote_fetcher = _QuoteFetcher(
        [
            DataFetchError("temporary"),
            (
                _quote("000003.SZ", 10.0, 10.0, 50.0, 3000.0, 1500.0),
                _quote("000004.SZ", 10.2, 10.0, 50.0, 4000.0, 2000.0),
            ),
        ]
    )
    fetcher = TencentMarketAggregateFetcher(
        symbols=["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
        quote_fetcher=quote_fetcher,
        batch_size=2,
    )

    snapshot = fetcher.fetch_aggregate()

    assert snapshot.status == "partial"
    assert snapshot.returned_count == 2
    assert snapshot.reported_count == 4
    assert snapshot.coverage_ratio == pytest.approx(0.5)


def test_fetcher_raises_when_all_tencent_batches_fail() -> None:
    quote_fetcher = _QuoteFetcher([DataFetchError("first"), DataFetchError("second")])
    fetcher = TencentMarketAggregateFetcher(
        symbols=["000001.SZ", "000002.SZ"],
        quote_fetcher=quote_fetcher,
        batch_size=1,
    )

    with pytest.raises(DataFetchError, match="所有批次请求失败"):
        fetcher.fetch_aggregate()


def test_fetcher_requires_a_local_stock_universe() -> None:
    fetcher = TencentMarketAggregateFetcher(quote_fetcher=_QuoteFetcher([]))

    with pytest.raises(DataFetchError, match="stock_basic"):
        fetcher.fetch_aggregate()
