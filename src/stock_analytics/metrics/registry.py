"""市场指标注册表。"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from stock_analytics.metrics.calculators import BUILTIN_METRIC_SPECS

if TYPE_CHECKING:
    from collections.abc import Iterable

    from stock_analytics.metrics.spec import EntityType, MetricDomain, MetricSpec


class MetricRegistry:
    """按指标元数据管理可计算指标。"""

    def __init__(self, specs: Iterable[MetricSpec] = ()) -> None:
        """初始化注册表。"""
        self._specs: dict[str, MetricSpec] = {}
        self.register_many(specs)

    @property
    def specs(self) -> MappingProxyType[str, MetricSpec]:
        """返回只读指标定义映射。"""
        return MappingProxyType(self._specs)

    def register(self, spec: MetricSpec) -> None:
        """注册一个指标定义。"""
        if spec.metric_id in self._specs:
            raise ValueError(f"重复注册指标: {spec.metric_id}")
        self._specs[spec.metric_id] = spec

    def register_many(self, specs: Iterable[MetricSpec]) -> None:
        """批量注册指标定义。"""
        for spec in specs:
            self.register(spec)

    def get(self, metric_id: str) -> MetricSpec:
        """按指标 ID 获取定义。"""
        try:
            return self._specs[metric_id]
        except KeyError as exc:
            raise KeyError(f"未知指标: {metric_id}") from exc

    def select(
        self,
        *,
        domain: MetricDomain | None = None,
        entity_type: EntityType | None = None,
    ) -> tuple[MetricSpec, ...]:
        """按领域和标的粒度筛选指标定义。"""
        specs = tuple(self._specs.values())
        if domain is not None:
            specs = tuple(spec for spec in specs if spec.domain == domain)
        if entity_type is not None:
            specs = tuple(spec for spec in specs if spec.entity_type == entity_type)
        return specs


def create_default_registry() -> MetricRegistry:
    """创建包含内置指标定义的注册表。"""
    return MetricRegistry(BUILTIN_METRIC_SPECS)
