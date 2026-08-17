"""Feature 特征定义契约与元数据规范。

涵盖 Aggregate（聚合量）、Indicator（指标）、Factor（横截面因子）、
Score（标准化评分）、Signal（离散信号）、Label（机器学习与回测标签）六大语义分类。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from stock.models.market import EntityType

if TYPE_CHECKING:
    from datetime import date, datetime


class FeatureKind(StrEnum):
    """特征语义六分类。"""

    AGGREGATE = "aggregate"  # 市场或行业聚合量（如市场总成交额、两融余额、上涨家数）
    INDICATOR = "indicator"  # 时序技术/统计指标（如 20日均线乖离、RSI、波动率、宽度占比）
    FACTOR = "factor"  # 可横截面比较与排序的因子（如 估值分位、动量 z-score、换手率因子）
    SCORE = "score"  # 标准化评分（固定 0-100 或 [-1, 1]，如 市场温度、行业景气度）
    SIGNAL = "signal"  # 离散信号或状态（布尔或枚举，如 多空金叉、超买超卖预警）
    LABEL = "label"  # 监督学习或回测标签（如 未来5日超额收益、持仓区间收益标签）


class FeatureUnit(StrEnum):
    """特征物理或标准化单位。"""

    CNY = "CNY"  # 人民币金额（元/亿元）
    SHARES = "shares"  # 股数/份额
    COUNT = "count"  # 家数/次数
    RATIO = "ratio"  # 比例/比率
    PERCENT = "percent"  # 百分数（如 2.5 表示 2.5%）
    PERCENTILE = "percentile"  # 历史分位数 (0~100)
    ZSCORE = "zscore"  # 标准化 Z-Score (通常无界，均值0方差1)
    SCORE_0_100 = "score_0_100"  # 0~100 综合评分
    BOOLEAN = "boolean"  # 布尔值 (0/1 或 True/False)
    UNKNOWN = "unknown"  # 未指定/复合


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """单个特征的不可变元数据契约。"""

    feature_id: str
    kind: FeatureKind
    entity_type: EntityType
    unit: FeatureUnit
    frequency: str = "1d"
    lookback_days: int = 1
    inputs: tuple[str, ...] = ()
    transform: str = ""
    universe: str = ""
    direction: str = "neutral"
    normalization: str = "none"
    definition_version: str = "v1"
    required_datasets: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    is_materialized_wide: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class FeatureValue:
    """单个特征在具体实体与日期的观测值。"""

    feature_id: str
    kind: FeatureKind
    entity_type: EntityType
    entity_id: str
    frequency: str
    observation_date: date
    available_at: datetime
    unit: FeatureUnit
    value_float: float | None = None
    value_str: str | None = None
    sample_size: int | None = None
    status: str = "ok"
    definition_version: str = "v1"
    source_watermark: str = ""
    input_fingerprint: str = ""


__all__ = [
    "EntityType",
    "FeatureKind",
    "FeatureSpec",
    "FeatureUnit",
    "FeatureValue",
]
