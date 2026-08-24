"""市场指标定义协议。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import polars as pl

from stock_core.models.market import EntityType

if TYPE_CHECKING:
    from stock_analytics.metrics.context import MetricContext


class MetricDomain(StrEnum):
    """指标所属分析领域。"""

    PERFORMANCE = "performance"
    BREADTH = "breadth"
    TREND = "trend"
    VOLATILITY = "volatility"
    LIQUIDITY = "liquidity"
    VALUATION = "valuation"
    FLOW = "flow"
    MACRO = "macro"
    DERIVATIVES = "derivatives"


class MetricFrequency(StrEnum):
    """指标计算频率。"""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


MetricCalculator = Callable[["MetricContext", "MetricSpec"], pl.DataFrame]


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """单个指标的稳定元数据定义。"""

    metric_id: str
    name: str
    domain: MetricDomain
    entity_type: EntityType
    frequency: MetricFrequency = MetricFrequency.DAILY
    windows: tuple[int, ...] = ()
    required_datasets: tuple[str, ...] = ()
    output_columns: tuple[str, ...] = ()
    description: str = ""


__all__ = [
    "EntityType",
    "MetricCalculator",
    "MetricDomain",
    "MetricFrequency",
    "MetricSpec",
]
