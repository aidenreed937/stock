"""市场聚合抓取、缓存与留档协调器。"""

from __future__ import annotations

from datetime import datetime
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

    def run(self, *, now: datetime | None = None) -> CachedMarketAggregate:
        """获取一条市场聚合结果；网络失败时回退到当天缓存。"""
        current_time = now or datetime.now(_SHANGHAI_TZ)
        try:
            snapshot = self.fetcher.fetch_aggregate()
            self.cache.put(snapshot)
            if self.recorder is not None:
                self.recorder.append([snapshot], now=snapshot.received_at)
        except DataFetchError:
            cached = self.cache.lookup(self.fetcher.source, now=current_time)
            if cached is not None:
                return cached
            raise
        cached = self.cache.lookup(
            self.fetcher.source,
            now=current_time,
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
