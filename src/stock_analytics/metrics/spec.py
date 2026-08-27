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


class MetricUnit(StrEnum):
    """指标物理或标准化单位。

    取值与 :class:`stock_analytics.features.spec.FeatureUnit` 对齐，
    避免跨层单位语义漂移，并遵守 metrics→features 依赖门禁
    （metrics 不依赖 features）。
    """

    CNY = "CNY"  # 人民币金额（元/亿元）
    SHARES = "shares"  # 股数/份额
    COUNT = "count"  # 家数/次数
    RATIO = "ratio"  # 比例/比率（小数，如 0.03 表示 3%）
    PERCENT = "percent"  # 百分数（如 2.5 表示 2.5%）
    PERCENTILE = "percentile"  # 历史分位数 (0~100)
    ZSCORE = "zscore"  # 标准化 Z-Score (通常无界，均值0方差1)
    SCORE_0_100 = "score_0_100"  # 0~100 综合评分
    BOOLEAN = "boolean"  # 布尔值 (0/1 或 True/False)
    UNKNOWN = "unknown"  # 未指定/复合


MetricCalculator = Callable[["MetricContext", "MetricSpec"], pl.DataFrame]


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """单个指标的稳定元数据定义。"""

    metric_id: str
    name: str
    domain: MetricDomain
    entity_type: EntityType
    unit: MetricUnit = MetricUnit.UNKNOWN
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
    "MetricUnit",
]
