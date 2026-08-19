"""全市场聚合快照的缓存、降级与 RAW 留档测试。"""

from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.realtime.cache import MarketAggregateCache, MarketAggregateFreshness
from stock_analytics.realtime.market_aggregate_monitor import MarketAggregateMonitor
from stock_core.exceptions import DataFetchError
from stock_data.fetcher.realtime.market_aggregate import (
    BaseMarketAggregateFetcher,
    MarketAggregateSnapshot,
)
from stock_data.fetcher.realtime.market_aggregate_recorder import (
    MarketAggregateSnapshotRecorder,
)


class _Fetcher(BaseMarketAggregateFetcher):
    source = "eastmoney"

    def __init__(self, snapshot: MarketAggregateSnapshot, *, fail: bool = False) -> None:
        self.snapshot = snapshot
        self.fail = fail

    def fetch_aggregate(self) -> MarketAggregateSnapshot:
        if self.fail:
            raise DataFetchError("network down")
        return self.snapshot


def _snapshot(received_at: datetime) -> MarketAggregateSnapshot:
    return MarketAggregateSnapshot(
        status="valid",
        received_at=received_at,
        reported_count=4,
        returned_count=4,
        priced_count=4,
        change_count=4,
        amount_count=4,
        market_cap_count=4,
        coverage_ratio=1.0,
        advance_count=2,
        decline_count=1,
        flat_count=1,
        advance_share=0.5,
        decline_share=0.25,
        advance_decline_ratio=2.0,
        strong_up_threshold_pct=5.0,
        strong_up_count=1,
        strong_down_count=1,
        strong_up_share=0.25,
        strong_down_share=0.25,
        median_pct_change=1.0,
        pct_change_p25=-1.25,
        pct_change_p75=4.0,
        weighted_pct_change=-0.8,
        amount_total_yuan=500.0,
        total_market_value_yuan=10000.0,
        free_float_market_value_yuan=5000.0,
        free_float_turnover_pct=10.0,
        amount_top_5pct_share=0.6,
    )


def test_market_aggregate_cache_tracks_fresh_stale_expired_and_date_boundary() -> None:
    received_at = datetime(2026, 8, 19, 10, 0)
    cache = MarketAggregateCache(fresh_ttl_seconds=30, max_age_seconds=300)
    snapshot = _snapshot(received_at)
    cache.put(snapshot)

    assert (
        cache.lookup("eastmoney", now=received_at + timedelta(seconds=1)).freshness
        == MarketAggregateFreshness.FRESH
    )
    assert (
        cache.lookup("eastmoney", now=received_at + timedelta(seconds=31)).freshness
        == MarketAggregateFreshness.STALE
    )
    assert (
        cache.lookup("eastmoney", now=received_at + timedelta(seconds=301)).freshness
        == MarketAggregateFreshness.EXPIRED
    )
    assert cache.lookup("eastmoney", now=datetime(2026, 8, 20, 10, 0)) is None


def test_monitor_falls_back_to_same_day_cached_snapshot() -> None:
    received_at = datetime(2026, 8, 19, 10, 0)
    fetcher = _Fetcher(_snapshot(received_at))
    monitor = MarketAggregateMonitor(fetcher)

    first = monitor.run(now=received_at)
    fetcher.fail = True
    fallback = monitor.run(now=received_at + timedelta(seconds=61))

    assert first.freshness == MarketAggregateFreshness.FRESH
    assert fallback.freshness == MarketAggregateFreshness.STALE
    assert fallback.snapshot.received_at == received_at


def test_monitor_uses_snapshot_time_for_cross_midnight_cache_and_raw_partition(
    tmp_path: Path,
) -> None:
    requested_at = datetime(2026, 8, 19, 23, 59, 59)
    received_at = requested_at + timedelta(seconds=2)
    recorder = MarketAggregateSnapshotRecorder(root=tmp_path)
    monitor = MarketAggregateMonitor(_Fetcher(_snapshot(received_at)), recorder=recorder)

    result = monitor.run(now=requested_at)

    assert result.freshness == MarketAggregateFreshness.FRESH
    targets = list((tmp_path / "date=2026-08-20" / "hour=00").glob("*.parquet"))
    assert len(targets) == 1
    saved = pl.read_parquet(targets[0])
    assert saved["source"].to_list() == ["eastmoney"]
    assert saved["returned_count"].to_list() == [4]


def test_monitor_raises_when_fetch_fails_without_cache() -> None:
    now = datetime(2026, 8, 19, 10, 0)
    monitor = MarketAggregateMonitor(_Fetcher(_snapshot(now), fail=True))

    with pytest.raises(DataFetchError, match="network down"):
        monitor.run(now=now)
