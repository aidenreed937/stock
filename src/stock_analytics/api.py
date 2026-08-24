"""统一 metrics / features 双轨调度门面 (Analytics Facade)。

本模块提供量化分析引擎的**统一顶层访问入口**，聚合两条体系：

- **metrics（时序指标体系）**：`MetricRegistry` + `MetricEngine` 批量调度，
  产出 `MetricResult`；统一入口 `compute_metrics` / `list_metrics`。
- **features（截面特征库）**：`FeatureRegistry` 元数据 + `FeatureStore`
  物化宽表；统一入口 `compute_features` / `list_features`。

设计原则：
    - 纯门面：仅聚合下层，不改动既有 `metrics/` / `features/` 实现；
    - 边界合规：本模块位于 `stock_analytics` 顶层，不受 `LAYER_FORBIDDEN`
      限制（该约束仅作用于 primitives/metrics/features/marts 层），
      但自身不反向被下层依赖；
    - 缺省安全：未显式传入上下文时按门面日期构造 `MetricContext` /
      `FeatureStore`；物化宽表未构建时返回空表（fail-closed）。

定位说明：metrics 与 features 不是同一层级的"重复实现"，而是
**粒度/语义分工**——指标=多实体时序状态（MARKET/STOCK/INDUSTRY/DERIVATIVES…），
特征=截面暴露。既有 `marts/market_temperature.py` 是唯一同时使用
MetricEngine 与 FeatureStore 的构建入口，本门面提供同类能力的统一封装。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.features.registry import FeatureRegistry
from stock_analytics.features.spec import FeatureKind, FeatureSpec
from stock_analytics.features.store import FeatureStore
from stock_analytics.metrics.context import MetricContext
from stock_analytics.metrics.engine import MetricEngine
from stock_analytics.metrics.registry import MetricRegistry, create_default_registry
from stock_analytics.metrics.spec import MetricDomain, MetricSpec
from stock_core.models.market import EntityType

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from stock_analytics.metrics.models import MetricResult
    from stock_analytics.metrics.spec import MetricCalculator


@dataclass(slots=True)
class AnalyticsContext:
    """统一指标/特征计算的轻量门面上下文。

    同时携带时序日期（target_date/start/end）与两条体系的底层依赖
    （MetricContext / FeatureStore），未显式传入时按日期自动构造。
    """

    target_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    metric_context: MetricContext | None = None
    feature_store: FeatureStore | None = None

    def resolve_metric_context(self) -> MetricContext:
        """返回指标层上下文；未显式传入时以门面日期构造。"""
        if self.metric_context is not None:
            return self.metric_context
        return MetricContext(
            target_date=self.target_date,
            start_date=self.start_date,
            end_date=self.end_date,
        )

    def resolve_feature_store(self) -> FeatureStore:
        """返回特征存储；未显式传入时以默认路径构造。"""
        if self.feature_store is not None:
            return self.feature_store
        return FeatureStore()


def compute_metrics(
    metric_ids: Sequence[str],
    context: AnalyticsContext | None = None,
    *,
    registry: MetricRegistry | None = None,
    calculators: Mapping[str, MetricCalculator] | None = None,
) -> tuple[MetricResult, ...]:
    """统一入口批量计算指标。

    Args:
        metric_ids: 指标 ID 列表（如 ["market_turnover", "sw_industry_pe"]）。
        context: 门面上下文；为 None 时使用默认日期（无日期窗口）。
        registry: 自定义指标注册表；缺省使用内置注册表（67 个指标）。
        calculators: 自定义计算器映射；缺省使用内置计算器。

    Returns:
        MetricResult 元组（每指标一个），失败时抛 KeyError/ValueError。

    Raises:
        KeyError: 指标 ID 未注册或未绑定计算器。
    """
    ctx = context or AnalyticsContext()
    engine = MetricEngine(registry=registry, calculators=calculators)
    return engine.compute(metric_ids, ctx.resolve_metric_context())


def compute_features(
    feature_ids: Sequence[str],
    context: AnalyticsContext | None = None,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """统一入口读取物化的特征宽表（列投影为 feature_ids）。

    从 `FeatureStore.market_daily` 物化宽表按列投影读取特征；
    显式 start_date/end_date 优先于门面上下文日期。
    返回结果始终包含 trade_date 列（便于时序使用）。

    Args:
        feature_ids: 特征 ID 列表（物化宽表中的列名）。
        context: 门面上下文；为 None 时使用默认 FeatureStore。
        start_date: 起始日期（优先于 context.start_date）。
        end_date: 结束日期（优先于 context.end_date）。

    Returns:
        物化特征宽表子集（含 trade_date 列）；宽表未构建时返回空表（fail-closed）。
    """
    ctx = context or AnalyticsContext()
    effective_start = start_date or ctx.start_date
    effective_end = end_date or ctx.end_date
    store = ctx.resolve_feature_store()
    columns: Sequence[str] | None = list(feature_ids) if feature_ids else None
    if columns is not None and "trade_date" not in columns:
        columns = ["trade_date", *columns]
    return store.get_market_daily(
        start_date=effective_start,
        end_date=effective_end,
        columns=columns,
    )


def list_metrics(
    *,
    domain: MetricDomain | None = None,
    entity_type: EntityType | None = None,
) -> tuple[MetricSpec, ...]:
    """统一指标目录（可按领域/实体粒度筛选）。

    Args:
        domain: 指标领域（如 MetricDomain.VALUATION / DERIVATIVES）。
        entity_type: 实体粒度（如 EntityType.MARKET / INDUSTRY）。

    Returns:
        匹配的指标定义元组（缺省返回全部内置 67 个指标）。
    """
    registry = create_default_registry()
    return registry.select(domain=domain, entity_type=entity_type)


def list_features(
    *,
    kind: FeatureKind | None = None,
    entity_type: EntityType | None = None,
) -> tuple[FeatureSpec, ...]:
    """统一特征目录（可按语义类别/实体粒度筛选）。

    Args:
        kind: 特征语义类别（如 FeatureKind.FACTOR / LABEL）。
        entity_type: 实体粒度（如 EntityType.MARKET / STOCK）。

    Returns:
        匹配的特征定义元组（缺省返回全部内置特征）。
    """
    specs = FeatureRegistry.list_all()
    if kind is not None:
        specs = [spec for spec in specs if spec.kind == kind]
    if entity_type is not None:
        specs = [spec for spec in specs if spec.entity_type == entity_type]
    return tuple(specs)


__all__ = [
    "AnalyticsContext",
    "compute_features",
    "compute_metrics",
    "list_features",
    "list_metrics",
]
