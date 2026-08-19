"""全市场聚合监控产物管线。"""

from stock_analytics.pipelines.market_aggregate.pipeline import (
    MarketAggregateRunResult,
    run_market_aggregate,
)

__all__ = ["MarketAggregateRunResult", "run_market_aggregate"]
