"""市场聚合抓取、缓存与留档协调器。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from zoneinfo import ZoneInfo

from stock_analytics.realtime.cache import (
    CachedMarketAggregate,
    MarketAggregateCache,
    MarketAggregateFreshness,
)
from stock_core.exceptions import DataFetchError
from stock_data.fetcher.realtime.market_aggregate import (
    BaseMarketAggregateFetcher,
    MarketAggregateSnapshot,
)
from stock_data.fetcher.realtime.market_aggregate_industry import (
    IndustryBreadthSnapshot,
    empty_industry_snapshot,
)
from stock_data.fetcher.realtime.market_aggregate_recorder import (
    MarketAggregateSnapshotRecorder,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class MarketAggregateMonitor:
    """协调全市场聚合快照、缓存降级和 RAW 留档。"""

    def __init__(
        self,
        fetcher: BaseMarketAggregateFetcher,
        *,
        cache: MarketAggregateCache | None = None,
        recorder: MarketAggregateSnapshotRecorder | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.cache = cache or MarketAggregateCache()
        self.recorder = recorder
        self._industry_snapshots: dict[date, IndustryBreadthSnapshot] = {}

    def run(self, *, now: datetime | None = None) -> CachedMarketAggregate:
        """获取一条市场聚合结果；网络失败时回退到当天缓存。"""
        current_time = now or datetime.now(_SHANGHAI_TZ)
        try:
            snapshot = self.fetcher.fetch_aggregate()
            return self._accept(snapshot, now=current_time)
        except DataFetchError:
            cached = self.cache.lookup(self.fetcher.source, now=current_time)
            if cached is not None:
                return cached
            raise

    def run_from_snapshot(
        self,
        snapshot: MarketAggregateSnapshot,
        *,
        now: datetime | None = None,
    ) -> CachedMarketAggregate:
        """登记一条已由外部抓取的快照并走缓存/留档；不再重复网络请求。"""
        current_time = now or datetime.now(_SHANGHAI_TZ)
        return self._accept(snapshot, now=current_time)

    def run_with_industry(
        self,
        industry_map: Mapping[str, str],
        *,
        min_members: int = 3,
        now: datetime | None = None,
    ) -> tuple[CachedMarketAggregate, IndustryBreadthSnapshot]:
        """获取市场与行业快照；失败时回退同日市场缓存并明确降级行业数据。"""
        current_time = now or datetime.now(_SHANGHAI_TZ)
        try:
            snapshot, industry = self.fetcher.fetch_aggregate_with_industry(
                industry_map,
                min_members=min_members,
            )
            cached = self._accept(snapshot, now=current_time)
            self._industry_snapshots[snapshot.quote_date] = industry
            return cached, industry
        except DataFetchError:
            fallback_cached = self.cache.lookup(self.fetcher.source, now=current_time)
            if fallback_cached is None:
                raise
            fallback_industry = self._industry_snapshots.get(fallback_cached.snapshot.quote_date)
            if fallback_industry is None:
                fallback_industry = empty_industry_snapshot(fallback_cached.snapshot)
            return fallback_cached, fallback_industry

    def _accept(
        self,
        snapshot: MarketAggregateSnapshot,
        *,
        now: datetime,
    ) -> CachedMarketAggregate:
        """将快照写入缓存（可选留档）并返回缓存读取结果。"""
        self.cache.put(snapshot)
        if self.recorder is not None:
            self.recorder.append([snapshot], now=snapshot.received_at)
        cached = self.cache.lookup(
            self.fetcher.source,
            now=now,
            quote_date=snapshot.quote_date,
        )
        if cached is None:
            raise DataFetchError("市场聚合快照写入缓存后无法读取")
        return cached


__all__ = [
    "CachedMarketAggregate",
    "MarketAggregateCache",
    "MarketAggregateFreshness",
    "MarketAggregateMonitor",
    "MarketAggregateSnapshot",
]
