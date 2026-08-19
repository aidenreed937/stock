"""实时行情数据源与快照留档。"""

from stock_data.fetcher.realtime.base import (
    BaseRealtimeFetcher,
    RealtimeQuote,
    normalize_local_symbol,
    to_tencent_symbol,
)
from stock_data.fetcher.realtime.market_aggregate import (
    BaseMarketAggregateFetcher,
    MarketAggregateFetcher,
    MarketAggregateSnapshot,
    TencentMarketAggregateFetcher,
)
from stock_data.fetcher.realtime.market_aggregate_recorder import (
    MarketAggregateSnapshotRecorder,
)
from stock_data.fetcher.realtime.recorder import RealtimeSnapshotRecorder
from stock_data.fetcher.realtime.tencent import TencentRealtimeFetcher

__all__ = [
    "BaseMarketAggregateFetcher",
    "BaseRealtimeFetcher",
    "MarketAggregateFetcher",
    "MarketAggregateSnapshot",
    "MarketAggregateSnapshotRecorder",
    "RealtimeQuote",
    "RealtimeSnapshotRecorder",
    "TencentMarketAggregateFetcher",
    "TencentRealtimeFetcher",
    "normalize_local_symbol",
    "to_tencent_symbol",
]
