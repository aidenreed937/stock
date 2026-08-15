"""流动性与交易热度类指标。"""

from stock.analytics.metrics.spec import MetricCalculator, MetricSpec

CALCULATORS: dict[str, MetricCalculator] = {}
METRIC_SPECS: tuple[MetricSpec, ...] = ()

__all__ = ["CALCULATORS", "METRIC_SPECS"]
