"""内置市场指标计算器集合。"""

from stock.analytics.metrics.calculators import (
    breadth,
    flow,
    liquidity,
    macro,
    performance,
    trend,
    valuation,
    volatility,
)
from stock.analytics.metrics.spec import MetricCalculator, MetricSpec

BUILTIN_METRIC_SPECS: tuple[MetricSpec, ...] = (
    *performance.METRIC_SPECS,
    *breadth.METRIC_SPECS,
    *trend.METRIC_SPECS,
    *volatility.METRIC_SPECS,
    *liquidity.METRIC_SPECS,
    *valuation.METRIC_SPECS,
    *flow.METRIC_SPECS,
    *macro.METRIC_SPECS,
)


def _merge_calculators(*mappings: dict[str, MetricCalculator]) -> dict[str, MetricCalculator]:
    """合并内置计算器，并拒绝重复指标 ID。"""
    calculators: dict[str, MetricCalculator] = {}
    for mapping in mappings:
        duplicates = set(calculators).intersection(mapping)
        if duplicates:
            duplicate_ids = ", ".join(sorted(duplicates))
            raise ValueError(f"重复注册指标计算器: {duplicate_ids}")
        calculators.update(mapping)
    return calculators


BUILTIN_CALCULATORS: dict[str, MetricCalculator] = _merge_calculators(
    performance.CALCULATORS,
    breadth.CALCULATORS,
    trend.CALCULATORS,
    volatility.CALCULATORS,
    liquidity.CALCULATORS,
    valuation.CALCULATORS,
    flow.CALCULATORS,
    macro.CALCULATORS,
)

__all__ = ["BUILTIN_CALCULATORS", "BUILTIN_METRIC_SPECS"]
