"""日度市场指标快照。"""

from dataclasses import dataclass
from datetime import date

from stock.analytics.metrics.models import MetricResult


@dataclass(frozen=True, slots=True)
class MarketMetricSnapshot:
    """一组指标在同一交易日的快照。"""

    trade_date: date
    results: tuple[MetricResult, ...]
