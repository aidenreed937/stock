"""市场指标定义协议。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from stock.analytics.metrics.context import MetricContext


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


class EntityType(StrEnum):
    """指标适用标的粒度。"""

    STOCK = "stock"
    INDEX = "index"
    INDUSTRY = "industry"
    ETF = "etf"
    MACRO = "macro"
    MARKET = "market"


class MetricFrequency(StrEnum):
    """指标计算频率。"""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class DiagnosticLevel(StrEnum):
    """指标诊断等级。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


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
