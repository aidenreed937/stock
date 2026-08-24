"""市场温度计评分结构生成。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.market_temperature.external_risk_scoring import build_external_risk
from stock_analytics.pipelines.market_temperature.freshness import (
    composite_freshness,
    dimension_freshness,
)
from stock_analytics.pipelines.market_temperature.score_components import (
    build_drivers,
    dimension_temperature,
    subgroup_temperatures,
)
from stock_analytics.pipelines.market_temperature.scoring_risk import _systemic_risk

if TYPE_CHECKING:
    from datetime import date

    from stock_reporting.interpretation.market_temperature.config import (
        DimensionConfig,
        MarketTemperatureConfig,
    )


def build_scores(
    config: MarketTemperatureConfig,
    *,
    as_of_date: date,
    facts: pl.DataFrame,
    previous_scores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """基于事实表生成评分 JSON 结构。

    当前版本只输出维度就绪状态，不把原始指标直接混合成温度分。
    """
    dimensions = [
        _dimension_score(
            config,
            item,
            facts,
        )
        for item in config.dimensions
    ]
    composite_temperature = _composite_temperature(dimensions)
    drivers = build_drivers(dimensions, composite_temperature, previous_scores)
    composite_status = (
        "ready" if all(item["temperature"] is not None for item in dimensions) else "partial"
    )
    if composite_temperature is None:
        composite_status = "pending"
    systemic_risk = _systemic_risk(composite_temperature, dimensions)
    external_risk = build_external_risk(config.external_risk, facts)
    return {
        "schema_version": config.schema_version,
        "as_of_date": as_of_date.isoformat(),
        "main_window": config.main_window,
        "short_windows": list(config.short_windows),
        "composite": {
            "temperature": composite_temperature,
            "status": composite_status,
            "reason": "按可用维度温度和默认权重重归一合成",
        },
        "systemic_risk": systemic_risk,
        "external_risk": external_risk,
        "drivers": drivers,
        "data_freshness": composite_freshness(dimensions),
        "dimensions": dimensions,
        "short_term": [_short_term_score(facts, window) for window in config.short_windows],
    }


def _short_term_score(facts: pl.DataFrame, window: int) -> dict[str, Any]:
    metric_id = f"short_term_temperature_{window}d"
    if facts.is_empty() or not {"metric_id", "dimension", "status"}.issubset(facts.columns):
        return {
            "window": window,
            "temperature": None,
            "status": "insufficient",
            "reason": "短线温度缺少 market_daily 事实输入",
        }
    frame = facts.filter((pl.col("dimension") == "short_term") & (pl.col("metric_id") == metric_id))
    if frame.is_empty() or "value_float" not in frame.columns:
        return {
            "window": window,
            "temperature": None,
            "status": "insufficient",
            "reason": "短线温度缺少对应窗口事实",
        }
    row = frame.tail(1).to_dicts()[0]
    value = row.get("value_float")
    status = str(row.get("status") or "insufficient")
    return {
        "window": window,
        "temperature": float(value) if value is not None else None,
        "status": "ready" if value is not None and status == "ok" else "insufficient",
        "reason": str(row.get("note") or "短线温度样本不足"),
    }


def _dimension_score(
    config: MarketTemperatureConfig,
    item: DimensionConfig,
    facts: pl.DataFrame,
) -> dict[str, Any]:
    dimension_id = item.id
    scored_metric_ids = _scored_metric_ids(item)
    configured_metric_count = len(scored_metric_ids)
    metric_count = _count_metric_facts(facts, dimension_id, scored_metric_ids)
    ok_metric_count = _count_metric_facts(facts, dimension_id, scored_metric_ids, status="ok")
    data_issue_count = _count_data_issues(config, facts, dimension_id)
    temperature = dimension_temperature(item, facts)
    subgroups = subgroup_temperatures(item, facts)
    temperature_source = "daily" if temperature is not None else None
    if temperature is None:
        for subgroup in ("activity", "slow"):
            fallback_temperature = subgroups[subgroup]
            if fallback_temperature is not None:
                temperature = fallback_temperature
                temperature_source = subgroup
                break
    status = "ready" if temperature is not None and data_issue_count == 0 else "pending"
    if metric_count == 0 and configured_metric_count:
        reason = "已配置指标，但本次未采集指标事实"
    elif metric_count == 0:
        reason = "该维度暂无默认 MetricEngine 指标，需由 DataCatalog 扩展事实补足"
    elif data_issue_count:
        reason = "存在数据水位缺口或滞后"
    elif temperature is None:
        reason = "部分指标计算失败或样本不足"
    elif ok_metric_count < metric_count:
        reason = "部分指标样本不足，已按可用温度子项合成"
    else:
        reason = "指标事实已温度化"
    if temperature_source in {"activity", "slow"}:
        source_label = {"activity": "活跃水位", "slow": "慢情绪"}[temperature_source]
        reason = f"主温度已降级为{source_label}口径；{reason}"
    return {
        "dimension_id": dimension_id,
        "name": item.name,
        "weight": item.weight,
        "temperature": temperature,
        "status": status,
        "configured_metric_count": configured_metric_count,
        "metric_count": metric_count,
        "ok_metric_count": ok_metric_count,
        "data_issue_count": data_issue_count,
        "temperature_source": temperature_source,
        "subgroups": subgroups,
        "data_freshness": dimension_freshness(facts, dimension_id, scored_metric_ids, item),
        "reason": reason,
    }


def _scored_metric_ids(item: DimensionConfig) -> set[str]:
    return {
        metric.metric_id
        for metric in item.metrics
        if metric.enabled and metric.weight > 0 and metric.subgroup in {"", "daily"}
    }


def _composite_temperature(dimensions: list[dict[str, Any]]) -> float | None:
    weighted_sum = 0.0
    weight_sum = 0.0
    for item in dimensions:
        temperature = item.get("temperature")
        if temperature is None:
            continue
        weight = float(item["weight"])
        weighted_sum += float(temperature) * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return round(weighted_sum / weight_sum, 2)


def _count_metric_facts(
    facts: pl.DataFrame,
    dimension_id: str,
    metric_ids: set[str],
    *,
    status: str | None = None,
) -> int:
    if not metric_ids:
        return 0
    return _count_facts(
        facts,
        dimension_id,
        "metric_value",
        status=status,
        metric_ids=metric_ids,
    )


def _count_facts(
    facts: pl.DataFrame,
    dimension_id: str,
    category: str,
    *,
    status: str | None = None,
    metric_ids: set[str] | None = None,
) -> int:
    if facts.is_empty():
        return 0
    frame = facts.filter((pl.col("dimension") == dimension_id) & (pl.col("category") == category))
    if metric_ids is not None:
        frame = frame.filter(pl.col("metric_id").is_in(metric_ids))
    if status is not None:
        frame = frame.filter(pl.col("status") == status)
    return frame.height


def _count_data_issues(
    config: MarketTemperatureConfig,
    facts: pl.DataFrame,
    dimension_id: str,
) -> int:
    required_keys = {
        (item.data_source, item.dataset)
        for item in config.datasets
        if item.dimension == dimension_id and item.required
    }
    if not required_keys or facts.is_empty():
        return 0
    frame = facts.filter(
        (pl.col("dimension") == dimension_id) & (pl.col("category") == "data_watermark")
    )
    count = 0
    for row in frame.to_dicts():
        key = (str(row["data_source"]), str(row["dataset"]))
        if key in required_keys and str(row["status"]) != "ok":
            count += 1
    return count


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
