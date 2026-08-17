"""通用市场指标层。"""

from stock.analytics.metrics.context import MetricContext
from stock.analytics.metrics.engine import MetricEngine
from stock.analytics.metrics.models import MetricResult
from stock.analytics.metrics.registry import MetricRegistry, create_default_registry
from stock.analytics.metrics.spec import (
    EntityType,
    MetricDomain,
    MetricFrequency,
    MetricSpec,
)

__all__ = [
    "EntityType",
    "MetricContext",
    "MetricDomain",
    "MetricEngine",
    "MetricFrequency",
    "MetricRegistry",
    "MetricResult",
    "MetricSpec",
    "create_default_registry",
]
