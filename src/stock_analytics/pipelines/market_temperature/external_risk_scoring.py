"""外盘风险状态评分。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_temperature.external_risk_config import (
        ExternalRiskConfig,
        ExternalShockRuleConfig,
    )


def build_external_risk(config: ExternalRiskConfig, facts: pl.DataFrame) -> dict[str, Any]:
    """按配置从事实表生成外盘背景、冲击和传导状态。"""
    rows_by_metric = _metric_rows(facts)
    background_pressure = _fact_value(rows_by_metric, config.background_pressure_metric_id)
    environment_temperature = _fact_value(
        rows_by_metric,
        config.environment_temperature_metric_id,
    )
    observations: list[dict[str, Any]] = []
    triggered_rules: list[dict[str, Any]] = []
    for rule in config.shock.rules:
        value = _fact_value(rows_by_metric, rule.metric_id)
        if value is None:
            continue
        observation = {
            "metric_id": rule.metric_id,
            "label": rule.label,
            "operator": rule.operator,
            "threshold": rule.threshold,
            "value": value,
            "unit": str(rows_by_metric[rule.metric_id].get("unit") or ""),
            "triggered": _matches_shock_rule(rule, value),
        }
        observations.append(observation)
        if observation["triggered"]:
            triggered_rules.append(observation)

    available_rule_count = len(observations)
    if not config.shock.rules or available_rule_count == 0:
        shock_status = "insufficient"
        transmission_status = config.transmission_status_insufficient
        message = config.message_insufficient
    elif len(triggered_rules) >= config.shock.min_trigger_count:
        shock_status = "short_term_shock"
        transmission_status = config.transmission_status_on_shock
        message = config.message_on_shock
    else:
        shock_status = "no_shock"
        transmission_status = config.transmission_status_without_shock
        message = config.message_without_shock

    return {
        "background_pressure": background_pressure,
        "environment_temperature": environment_temperature,
        "shock_status": shock_status,
        "transmission_status": transmission_status,
        "message": message,
        "triggered_rule_count": len(triggered_rules),
        "available_rule_count": available_rule_count,
        "required_trigger_count": config.shock.min_trigger_count,
        "triggered_rules": triggered_rules,
        "observations": observations,
        "observation_focus": list(config.observation_focus),
    }


def _metric_rows(facts: pl.DataFrame) -> dict[str, dict[str, Any]]:
    required = {"category", "metric_id", "status"}
    if facts.is_empty() or not required.issubset(facts.columns):
        return {}
    metric_rows = facts.filter((pl.col("category") == "metric_value") & (pl.col("status") == "ok"))
    return {
        str(row["metric_id"]): row
        for row in metric_rows.to_dicts()
        if row.get("value_float") is not None
    }


def _fact_value(rows_by_metric: dict[str, dict[str, Any]], metric_id: str) -> float | None:
    row = rows_by_metric.get(metric_id)
    return _as_float(row.get("value_float")) if row is not None else None


def _matches_shock_rule(rule: ExternalShockRuleConfig, value: float) -> bool:
    if rule.operator == "gte":
        return value >= rule.threshold
    if rule.operator == "gt":
        return value > rule.threshold
    if rule.operator == "lte":
        return value <= rule.threshold
    if rule.operator == "lt":
        return value < rule.threshold
    return value == rule.threshold


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
