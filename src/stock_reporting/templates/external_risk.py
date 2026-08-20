"""市场温度报告中的外盘风险展示。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stock_reporting.interpretation.market_temperature.bands import get_pressure_band

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_temperature.config import MarketTemperatureConfig


def external_risk_lines(
    scores: dict[str, Any],
    config: MarketTemperatureConfig,
) -> list[str]:
    """将外盘风险状态渲染为报告条目。"""
    risk = scores.get("external_risk")
    if not isinstance(risk, dict):
        return ["- 暂无外盘冲击状态产物。"]

    background = _as_float(risk.get("background_pressure"))
    environment = _as_float(risk.get("environment_temperature"))
    background_text = "不可判定"
    if background is not None:
        background_text = f"{get_pressure_band(background, config.bands)}（{background:.2f}）"

    shock_status = str(risk.get("shock_status") or "insufficient")
    transmission_status = str(risk.get("transmission_status") or "未知")
    triggered_rules = risk.get("triggered_rules")
    triggered = triggered_rules if isinstance(triggered_rules, list) else []
    if shock_status == "short_term_shock":
        shock_text = (
            "、".join(
                _format_external_observation(item) for item in triggered if isinstance(item, dict)
            )
            or "已触发配置阈值"
        )
    elif shock_status == "no_shock":
        shock_text = "未达到配置阈值"
    else:
        shock_text = "数据不足，暂不能判断"

    status_labels = {
        "pending_next_ashare_session": "待确认",
        "not_applicable": "未触发",
        "insufficient_external_data": "数据不足",
        "not_confirmed": "尚未确认",
        "short_term_transmitted": "短线已传导",
        "broad_risk_transmitted": "广泛风险已传导",
    }
    transmission_text = status_labels.get(transmission_status, transmission_status)
    focus = risk.get("observation_focus")
    focus_text = "、".join(str(item) for item in focus) if isinstance(focus, list) else ""

    lines = [
        f"- 外盘背景压力：{background_text}",
        f"- 外部环境温度：{_temperature_text(environment)}",
        f"- 冲击状态：{shock_status}",
        f"- 隔夜冲击：{shock_text}",
        f"- A 股传导状态：{transmission_text}（{transmission_status}）",
    ]
    if focus_text:
        lines.append(f"- 观察重点：{focus_text}")
    if risk.get("message"):
        lines.append(f"- 说明：{risk['message']}")
    return lines


def _format_external_observation(item: dict[str, Any]) -> str:
    label = str(item.get("label") or item.get("metric_id") or "外盘指标")
    value = _as_float(item.get("value"))
    if value is None:
        return f"{label} -"
    if str(item.get("unit")) == "percentage_point":
        return f"{label} {value:+.2f}个百分点"
    return f"{label} {value * 100:+.2f}%"


def _temperature_text(value: object) -> str:
    numeric = _as_float(value)
    return "不可判定" if numeric is None else f"{numeric:.2f}"


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None
