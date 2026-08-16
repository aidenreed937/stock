"""市场温度计评分结构生成。"""

from __future__ import annotations

from math import erf, sqrt
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from datetime import date

    from stock.analytics.market_temperature.config import DimensionConfig, MarketTemperatureConfig


def build_scores(
    config: MarketTemperatureConfig,
    *,
    as_of_date: date,
    facts: pl.DataFrame,
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
    composite_status = (
        "ready" if all(item["temperature"] is not None for item in dimensions) else "partial"
    )
    if composite_temperature is None:
        composite_status = "pending"
    systemic_risk = _systemic_risk(composite_temperature, dimensions)
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
        "dimensions": dimensions,
        "short_term": [
            {
                "window": window,
                "temperature": None,
                "status": "pending",
                "reason": "短线温度作为附加输出，待接入短窗指标公式",
            }
            for window in config.short_windows
        ],
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
    temperature = _dimension_temperature(item, facts)
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
        "reason": reason,
    }


def _scored_metric_ids(item: DimensionConfig) -> set[str]:
    return {metric.metric_id for metric in item.metrics if metric.enabled and metric.weight > 0}


def _dimension_temperature(item: DimensionConfig, facts: pl.DataFrame) -> float | None:
    if facts.is_empty():
        return None
    metric_rules = {
        metric.metric_id: (metric.direction, metric.weight)
        for metric in item.metrics
        if metric.enabled
    }
    frame = facts.filter(
        (pl.col("dimension") == item.id)
        & (pl.col("category") == "metric_value")
        & (pl.col("status") == "ok")
    )
    weighted_sum = 0.0
    weight_sum = 0.0
    for row in frame.to_dicts():
        metric_id = str(row["metric_id"])
        direction, weight = metric_rules.get(metric_id, ("positive", 1.0))
        if weight <= 0:
            continue
        temperature = _fact_temperature(row, direction)
        if temperature is None:
            continue
        weighted_sum += temperature * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return round(weighted_sum / weight_sum, 2)


def _fact_temperature(row: dict[str, Any], direction: str) -> float | None:
    value = row.get("value_float")
    if value is None:
        return None
    metric_id = str(row["metric_id"])
    numeric = float(value)
    is_percentile_temperature = metric_id == "valuation_temperature" or "percentile" in metric_id
    if row.get("unit") == "temperature" or is_percentile_temperature:
        temperature = numeric
    elif "zscore" in metric_id:
        temperature = _normal_cdf(numeric) * 100.0
    elif metric_id == "rsi_14d":
        temperature = numeric
    elif metric_id in {
        "advance_share",
        "above_ma20_share",
        "above_ma60_share",
        "above_ma120_share",
        "new_high_share_252d",
        "new_low_share_252d",
    }:
        temperature = numeric * 100.0
    elif metric_id in {"return_20d", "ma_bias_20d", "margin_balance_growth_20d"}:
        temperature = 50.0 + numeric * 500.0
    elif metric_id in {"main_money_net_inflow_share", "super_large_net_inflow_share"}:
        temperature = 50.0 + numeric * 1000.0
    else:
        return None
    return _apply_direction(temperature, direction)


def _apply_direction(value: float, direction: str) -> float:
    temperature = 100.0 - value if direction == "inverse" else value
    return _clip_temperature(temperature)


def _clip_temperature(value: float) -> float:
    return round(min(100.0, max(0.0, value)), 2)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


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


def _systemic_risk(
    composite_temperature: float | None,
    dimensions: list[dict[str, Any]],
) -> dict[str, Any]:
    values = {str(item["dimension_id"]): _as_float(item.get("temperature")) for item in dimensions}
    valuation = values.get("valuation")
    fund_flow = values.get("fund_flow")
    sentiment = values.get("sentiment")
    technical = values.get("technical")
    macro = values.get("macro_liquidity")
    fundamental = values.get("fundamental")
    red_flags: list[str] = []
    warnings: list[str] = []
    offsets: list[str] = []

    _add_valuation_risk(valuation, red_flags, warnings)
    _add_repair_quality_risk(technical, fund_flow, warnings)
    _add_sentiment_risk(sentiment, red_flags, warnings, offsets)
    _add_macro_risk(macro, red_flags, offsets)
    _add_fundamental_risk(fundamental, warnings, offsets)
    _add_composite_risk(composite_temperature, red_flags, warnings)
    level, status, message = _systemic_risk_level(red_flags, warnings)

    return {
        "level": level,
        "status": status,
        "message": message,
        "red_flags": red_flags,
        "warnings": warnings,
        "offsets": offsets,
    }


def _add_valuation_risk(
    value: float | None,
    red_flags: list[str],
    warnings: list[str],
) -> None:
    if value is not None and value >= 80:
        red_flags.append(f"估值面 {_temperature_text(value)} 已进入高温，安全边际收缩。")
    elif value is not None and value >= 70:
        warnings.append(f"估值面 {_temperature_text(value)} 偏高。")


def _add_repair_quality_risk(
    technical: float | None,
    fund_flow: float | None,
    warnings: list[str],
) -> None:
    if technical is not None and fund_flow is not None and technical >= 60 and fund_flow < 50:
        warnings.append("技术面偏热但资金面未同步确认，价格修复的资金质量需要继续观察。")


def _add_sentiment_risk(
    value: float | None,
    red_flags: list[str],
    warnings: list[str],
    offsets: list[str],
) -> None:
    if value is not None and value >= 80:
        red_flags.append(f"情绪面 {_temperature_text(value)} 进入高温，交易拥挤风险上升。")
    elif value is not None and value >= 70:
        warnings.append(f"情绪面 {_temperature_text(value)} 偏热。")
    elif value is not None and value < 60:
        offsets.append(f"情绪面 {_temperature_text(value)} 未明显过热。")


def _add_macro_risk(
    value: float | None,
    red_flags: list[str],
    offsets: list[str],
) -> None:
    if value is not None and value < 40:
        red_flags.append(f"宏观流动性 {_temperature_text(value)} 偏紧，对估值形成压力。")
    elif value is not None and value >= 50:
        offsets.append(f"宏观流动性 {_temperature_text(value)} 未构成主要压力。")


def _add_fundamental_risk(
    value: float | None,
    warnings: list[str],
    offsets: list[str],
) -> None:
    if value is not None and value >= 55:
        offsets.append(f"基本面 {_temperature_text(value)} 对风险偏好有一定支撑。")
    elif value is not None and value < 40:
        warnings.append(f"基本面 {_temperature_text(value)} 偏弱。")


def _add_composite_risk(
    value: float | None,
    red_flags: list[str],
    warnings: list[str],
) -> None:
    if value is not None and value >= 80:
        red_flags.append(f"综合温度 {_temperature_text(value)} 进入高温区。")
    elif value is not None and value >= 60:
        warnings.append(f"综合温度 {_temperature_text(value)} 处于偏热区。")


def _systemic_risk_level(red_flags: list[str], warnings: list[str]) -> tuple[str, str, str]:
    if len(red_flags) >= 2:
        return (
            "高",
            "high_systemic_risk",
            "多项系统性风险信号同时进入高位，应优先控制回撤和仓位暴露。",
        )
    if red_flags and warnings:
        return (
            "中等偏高",
            "elevated_systemic_risk",
            "存在明确风险源，但尚未形成全面风险扩散。",
        )
    if red_flags or len(warnings) >= 2:
        return (
            "中等",
            "moderate_systemic_risk",
            "系统性风险可控但不低，需要观察资金、情绪和宽度是否继续恶化。",
        )
    return (
        "低到中等",
        "contained_systemic_risk",
        "当前没有明显系统性风险共振，更多是结构性机会和结构性风险。",
    )


def _temperature_text(value: float) -> str:
    return f"{value:.2f}"


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
