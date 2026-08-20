"""市场温度计的子口径温度与跨期驱动计算。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.market_temperature.freshness import is_stale_metric
from stock_analytics.pipelines.market_temperature.metric_temperature import fact_temperature

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_temperature.config import DimensionConfig


def dimension_temperature(
    item: DimensionConfig,
    facts: pl.DataFrame,
    *,
    subgroup: str | None = None,
) -> float | None:
    """计算一个维度或子口径的加权温度。"""
    if facts.is_empty():
        return None
    metric_rules = {
        metric.metric_id: (
            metric.direction,
            metric.weight,
            metric.subgroup if metric.subgroup not in {"", "daily"} else "daily",
        )
        for metric in item.metrics
        if metric.enabled
    }
    target_subgroup = "daily" if subgroup in {None, "", "daily"} else subgroup
    frame = facts.filter(
        (pl.col("dimension") == item.id)
        & (pl.col("category") == "metric_value")
        & (pl.col("status") == "ok")
    )
    weighted_sum = 0.0
    weight_sum = 0.0
    for row in frame.to_dicts():
        metric_id = str(row["metric_id"])
        direction, weight, metric_subgroup = metric_rules.get(
            metric_id,
            ("positive", 1.0, "daily"),
        )
        if metric_subgroup != target_subgroup or weight <= 0:
            continue
        if is_stale_metric(row, item):
            weight *= item.stale_weight_scale
        temperature = fact_temperature(row, direction)
        if temperature is None:
            continue
        weighted_sum += temperature * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return round(weighted_sum / weight_sum, 2)


def subgroup_temperatures(
    item: DimensionConfig,
    facts: pl.DataFrame,
) -> dict[str, float | None]:
    """计算活跃水位和慢情绪子口径温度。"""
    return {
        subgroup: dimension_temperature(item, facts, subgroup=subgroup)
        for subgroup in ("activity", "slow")
    }


def build_drivers(
    current_dimensions: list[dict[str, Any]],
    current_composite: float | None,
    previous_scores: dict[str, Any] | None,
) -> dict[str, Any]:
    """构造跨期维度边际贡献，供机器和报告层复用。"""
    if previous_scores is None:
        return {"status": "no_comparison"}

    previous_dimensions = {
        str(item.get("dimension_id")): item
        for item in previous_scores.get("dimensions", [])
        if isinstance(item, dict) and item.get("dimension_id")
    }
    contributors: list[dict[str, Any]] = []
    for current in current_dimensions:
        dimension_id = str(current.get("dimension_id") or "")
        previous = previous_dimensions.get(dimension_id)
        current_temperature = _as_float(current.get("temperature"))
        previous_temperature = (
            _as_float(previous.get("temperature")) if previous is not None else None
        )
        weight = _as_float(current.get("weight"))
        if not dimension_id or current_temperature is None or previous_temperature is None:
            continue
        if weight is None:
            continue
        delta = current_temperature - previous_temperature
        weighted_delta = delta * weight
        contributors.append(
            {
                "dimension_id": dimension_id,
                "name": str(current.get("name") or dimension_id),
                "delta": round(delta, 2),
                "weight": weight,
                "weighted_delta": round(weighted_delta, 2),
                "direction": "warming" if weighted_delta >= 0 else "cooling",
            }
        )

    comparison_as_of = previous_scores.get("as_of_date")
    if not contributors:
        result: dict[str, Any] = {"status": "insufficient"}
        if comparison_as_of is not None:
            result["comparison_as_of"] = comparison_as_of
        return result

    contributors.sort(key=lambda item: abs(float(item["weighted_delta"])), reverse=True)
    top_contributors = contributors[:3]
    composite_delta = None
    previous_composite = previous_scores.get("composite", {})
    if isinstance(previous_composite, dict):
        previous_temperature = _as_float(previous_composite.get("temperature"))
        if current_composite is not None and previous_temperature is not None:
            composite_delta = round(current_composite - previous_temperature, 2)

    if composite_delta is None:
        summary = (
            "综合温度变化无法比较，主要可比维度由"
            + "、".join(f"{item['name']}({float(item['delta']):+.2f})" for item in top_contributors)
            + "迁移"
        )
    else:
        direction = "上升" if composite_delta >= 0 else "下降"
        summary = (
            f"综合温度{direction}主要由"
            + "、".join(f"{item['name']}({float(item['delta']):+.2f})" for item in top_contributors)
            + "迁移驱动"
        )
    return {
        "status": "ok",
        "comparison_as_of": comparison_as_of,
        "composite_delta": composite_delta,
        "summary": summary,
        "top_contributors": top_contributors,
    }


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
