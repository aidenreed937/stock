"""市场指标统一调度入口。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock.analytics.metrics.calculators import BUILTIN_CALCULATORS
from stock.analytics.metrics.context import MetricContext
from stock.analytics.metrics.datasets.schema import require_columns
from stock.analytics.metrics.models import MetricResult
from stock.analytics.metrics.registry import MetricRegistry, create_default_registry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from stock.analytics.metrics.spec import MetricCalculator


class MetricEngine:
    """根据注册表批量调度市场指标计算。"""

    def __init__(
        self,
        registry: MetricRegistry | None = None,
        calculators: Mapping[str, MetricCalculator] | None = None,
    ) -> None:
        """初始化指标引擎。"""
        self.registry = registry or create_default_registry()
        self.calculators = dict(BUILTIN_CALCULATORS if calculators is None else calculators)

    def compute(
        self,
        metric_ids: Sequence[str],
        context: MetricContext | None = None,
    ) -> tuple[MetricResult, ...]:
        """按指标 ID 批量计算。"""
        run_context = context or MetricContext()
        results: list[MetricResult] = []
        for metric_id in metric_ids:
            spec = self.registry.get(metric_id)
            calculator = self.calculators.get(metric_id)
            if calculator is None:
                raise KeyError(f"指标未绑定计算器: {metric_id}")
            frame = calculator(run_context, spec)
            require_columns(frame, spec.output_columns, metric_id)
            results.append(
                MetricResult(
                    metric_id=metric_id,
                    trade_date=run_context.resolve_end_date(),
                    frame=frame,
                )
            )
        return tuple(results)
