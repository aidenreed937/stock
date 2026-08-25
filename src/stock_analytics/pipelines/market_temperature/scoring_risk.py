"""市场温度计系统性风险评分。"""

from __future__ import annotations

from typing import Any


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
    triggered_rules: list[dict[str, Any]] = []

    _add_valuation_risk(valuation, red_flags, warnings, triggered_rules)
    _add_repair_quality_risk(technical, fund_flow, warnings, triggered_rules)
    _add_sentiment_risk(sentiment, red_flags, warnings, offsets, triggered_rules)
    _add_macro_risk(macro, red_flags, offsets, triggered_rules)
    _add_fundamental_risk(fundamental, warnings, offsets, triggered_rules)
    _add_composite_risk(composite_temperature, red_flags, warnings, triggered_rules)
    level, status, message = _systemic_risk_level(red_flags, warnings)

    return {
        "level": level,
        "status": status,
        "message": message,
        "red_flags": red_flags,
        "warnings": warnings,
        "offsets": offsets,
        "decision_trace": {
            "rule_version": "systemic-risk-v1",
            "inputs": {**values, "composite": composite_temperature},
            "triggered_rules": triggered_rules,
            "final_level": level,
            "final_status": status,
        },
    }


def _add_valuation_risk(
    value: float | None,
    red_flags: list[str],
    warnings: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    if value is not None and value >= 80:
        message = f"估值面 {_temperature_text(value)} 已进入高温，安全边际收缩。"
        red_flags.append(message)
        _add_rule(triggered_rules, "valuation_gte_80", "red_flag", value, 80, message)
    elif value is not None and value >= 70:
        message = f"估值面 {_temperature_text(value)} 偏高。"
        warnings.append(message)
        _add_rule(triggered_rules, "valuation_gte_70", "warning", value, 70, message)


def _add_repair_quality_risk(
    technical: float | None,
    fund_flow: float | None,
    warnings: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    if technical is not None and fund_flow is not None and technical >= 60 and fund_flow < 50:
        message = "技术面偏热但资金面未同步确认，价格修复的资金质量需要继续观察。"
        warnings.append(message)
        _add_rule(
            triggered_rules,
            "technical_gte_60_and_fund_flow_lt_50",
            "warning",
            {"technical": technical, "fund_flow": fund_flow},
            {"technical": 60, "fund_flow": 50},
            message,
        )


def _add_sentiment_risk(
    value: float | None,
    red_flags: list[str],
    warnings: list[str],
    offsets: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    if value is not None and value >= 80:
        message = f"情绪面 {_temperature_text(value)} 进入高温，交易拥挤风险上升。"
        red_flags.append(message)
        _add_rule(triggered_rules, "sentiment_gte_80", "red_flag", value, 80, message)
    elif value is not None and value >= 70:
        message = f"情绪面 {_temperature_text(value)} 偏热。"
        warnings.append(message)
        _add_rule(triggered_rules, "sentiment_gte_70", "warning", value, 70, message)
    elif value is not None and value < 60:
        message = f"情绪面 {_temperature_text(value)} 未明显过热。"
        offsets.append(message)
        _add_rule(triggered_rules, "sentiment_lt_60", "offset", value, 60, message)


def _add_macro_risk(
    value: float | None,
    red_flags: list[str],
    offsets: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    if value is not None and value < 40:
        message = f"宏观流动性 {_temperature_text(value)} 偏紧，对估值形成压力。"
        red_flags.append(message)
        _add_rule(triggered_rules, "macro_liquidity_lt_40", "red_flag", value, 40, message)
    elif value is not None and value >= 50:
        message = f"宏观流动性 {_temperature_text(value)} 未构成主要压力。"
        offsets.append(message)
        _add_rule(triggered_rules, "macro_liquidity_gte_50", "offset", value, 50, message)


def _add_fundamental_risk(
    value: float | None,
    warnings: list[str],
    offsets: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    if value is not None and value >= 55:
        message = f"基本面 {_temperature_text(value)} 对风险偏好有一定支撑。"
        offsets.append(message)
        _add_rule(triggered_rules, "fundamental_gte_55", "offset", value, 55, message)
    elif value is not None and value < 40:
        message = f"基本面 {_temperature_text(value)} 偏弱。"
        warnings.append(message)
        _add_rule(triggered_rules, "fundamental_lt_40", "warning", value, 40, message)


def _add_composite_risk(
    value: float | None,
    red_flags: list[str],
    warnings: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    if value is not None and value >= 80:
        message = f"综合温度 {_temperature_text(value)} 进入高温区。"
        red_flags.append(message)
        _add_rule(triggered_rules, "composite_gte_80", "red_flag", value, 80, message)
    elif value is not None and value >= 60:
        message = f"综合温度 {_temperature_text(value)} 处于偏热区。"
        warnings.append(message)
        _add_rule(triggered_rules, "composite_gte_60", "warning", value, 60, message)


def _add_rule(
    triggered_rules: list[dict[str, Any]],
    rule_id: str,
    category: str,
    actual: Any,
    threshold: Any,
    message: str,
) -> None:
    triggered_rules.append(
        {
            "rule_id": rule_id,
            "category": category,
            "actual": actual,
            "threshold": threshold,
            "message": message,
        }
    )


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


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
