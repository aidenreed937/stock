"""市场温度计指标的历史窗口选择。"""

from datetime import date, timedelta

from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.engine import MetricEngine
from stock_core.contracts import MarketDataCatalog

_LOOKBACK_BY_DOMAIN = {
    "valuation": 365 * 12,
    "performance": 252 * 3,
    "trend": 252 * 3,
    "breadth": 252 * 3,
    "volatility": 252 * 3,
    "flow": 1250 * 3,
    "liquidity": 1250 * 3,
}


def metric_lookback_days(engine: MetricEngine, metric_id: str) -> int:
    """按指标领域选择事实采集所需的最小历史窗口。"""
    domain = engine.registry.get(metric_id).domain.value
    return _LOOKBACK_BY_DOMAIN.get(domain, 365 * 7)


def build_metric_context(
    catalog: MarketDataCatalog, as_of_date: date, lookback_days: int
) -> MetricContext:
    """构造带领域历史窗口的指标上下文。"""
    return MetricContext(
        catalog=catalog,
        target_date=as_of_date,
        start_date=as_of_date - timedelta(days=lookback_days),
        end_date=as_of_date,
    )


def context_for_metric(
    contexts: dict[int, MetricContext],
    engine: MetricEngine,
    catalog: MarketDataCatalog,
    as_of_date: date,
    metric_id: str,
) -> MetricContext:
    """获取并复用指标所需的历史窗口上下文。"""
    lookback_days = metric_lookback_days(engine, metric_id)
    if lookback_days not in contexts:
        contexts[lookback_days] = build_metric_context(catalog, as_of_date, lookback_days)
    return contexts[lookback_days]
