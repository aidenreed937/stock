"""市场温度计系统性风险评分（Step 1/2/3 修正版）。

语义（Step 1，2026-08-28）：`risk_level` 是"温度读数可信度"——低 = 各维度共振
干净、读数可靠；高 = 存在硬性风险事件（估值/情绪/宏观/背离），读数可能被污染
或滞后。它不是价格收益预测器（实测 risk=高 后价格 fwd20 +2.28%）；消费方应按
"温度真伪确认器"使用（见 docs/research/temperature_signal_calibration.md 8.8/8.9）。

规则手术（Step 2，8.9.1 审计结论）：
  - valuation 原 80/70 在 988 天零触发（峰值 69.2）→ 阈值改为分位可达值 60/55；
  - macro 原 <40 死规则（国内口径 min=46.1）→ 去红旗，改为国内口径 <50 告警；
  - composite 原 80 死规则（峰值 68.6）→ 红旗收敛到 65（与高温极端一致）；
  - sentiment >=80 触发后 fwd20 +2.44%（方向存疑）→ 降级为 warning，
    不参与红旗表决（sentiment_red 配置为不可达上界，仅保留触发记录）。

配置化（Step 3）：全部阈值来自 `SystemicRiskConfig`（config.systemic_risk），
代码不再硬编码；不传 config 时使用默认值（与上述校准值一致）。
"""

from __future__ import annotations

from typing import Any

from stock_core.config.analytics_market_temperature import SystemicRiskConfig


def _systemic_risk(
    composite_temperature: float | None,
    dimensions: list[dict[str, Any]],
    fast_slow: dict[str, Any] | None = None,
    config: SystemicRiskConfig | None = None,
) -> dict[str, Any]:
    cfg = config or SystemicRiskConfig()
    values = {str(item["dimension_id"]): _as_float(item.get("temperature")) for item in dimensions}
    valuation = values.get("valuation")
    fund_flow = values.get("fund_flow")
    sentiment = values.get("sentiment")
    technical = values.get("technical")
    macro = values.get("macro_liquidity")
    fundamental = values.get("fundamental")
    macro_domestic = _macro_domestic_temperature(dimensions)
    fast = _as_float(fast_slow.get("fast_temperature")) if fast_slow else None
    slow = _as_float(fast_slow.get("slow_temperature")) if fast_slow else None
    divergence = _as_float(fast_slow.get("divergence")) if fast_slow else None
    red_flags: list[str] = []
    warnings: list[str] = []
    offsets: list[str] = []
    triggered_rules: list[dict[str, Any]] = []

    _add_valuation_risk(valuation, cfg, red_flags, warnings, triggered_rules)
    _add_repair_quality_risk(technical, fund_flow, cfg, warnings, triggered_rules)
    _add_sentiment_risk(sentiment, cfg, red_flags, warnings, offsets, triggered_rules)
    _add_macro_risk(macro, macro_domestic, cfg, warnings, offsets, triggered_rules)
    _add_fundamental_risk(fundamental, cfg, warnings, offsets, triggered_rules)
    _add_composite_risk(composite_temperature, cfg, red_flags, warnings, triggered_rules)
    _add_divergence_risk(fast, slow, divergence, cfg, red_flags, offsets, triggered_rules)
    level, status, message = _systemic_risk_level(red_flags, warnings)

    return {
        "level": level,
        "status": status,
        "message": message,
        "red_flags": red_flags,
        "warnings": warnings,
        "offsets": offsets,
        "semantics": "temperature_trust",  # Step 1: 明确为温度读数可信度，非价格风险预测
        "decision_trace": {
            "rule_version": cfg.rules_version,
            "inputs": {
                **values,
                "composite": composite_temperature,
                "macro_liquidity_domestic": macro_domestic,
                "fast_slow": (
                    {"fast_temperature": fast, "slow_temperature": slow, "divergence": divergence}
                    if fast_slow
                    else None
                ),
            },
            "triggered_rules": triggered_rules,
            "final_level": level,
            "final_status": status,
        },
    }


def _macro_domestic_temperature(dimensions: list[dict[str, Any]]) -> float | None:
    """从宏观流动性维度子口径中取国内流动性读数（Phase 2 规则切换输入）。"""
    for item in dimensions:
        if str(item.get("dimension_id")) != "macro_liquidity":
            continue
        subgroups = item.get("subgroups")
        if not isinstance(subgroups, dict):
            return None
        return _as_float(subgroups.get("domestic"))
    return None


def _add_valuation_risk(
    value: float | None,
    cfg: SystemicRiskConfig,
    red_flags: list[str],
    warnings: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    if value is not None and value >= cfg.valuation_red:
        message = f"估值面 {_temperature_text(value)} 已进入高温，安全边际收缩。"
        red_flags.append(message)
        _add_rule(
            triggered_rules,
            f"valuation_gte_{cfg.valuation_red:g}",
            "red_flag",
            value,
            cfg.valuation_red,
            message,
        )
    elif value is not None and value >= cfg.valuation_warning:
        message = f"估值面 {_temperature_text(value)} 偏高。"
        warnings.append(message)
        _add_rule(
            triggered_rules,
            f"valuation_gte_{cfg.valuation_warning:g}",
            "warning",
            value,
            cfg.valuation_warning,
            message,
        )


def _add_repair_quality_risk(
    technical: float | None,
    fund_flow: float | None,
    cfg: SystemicRiskConfig,
    warnings: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    if (
        technical is not None
        and fund_flow is not None
        and technical >= cfg.technical_gte
        and fund_flow < cfg.fund_flow_lt
    ):
        message = "技术面偏热但资金面未同步确认，价格修复的资金质量需要继续观察。"
        warnings.append(message)
        _add_rule(
            triggered_rules,
            f"technical_gte_{cfg.technical_gte:g}_and_fund_flow_lt_{cfg.fund_flow_lt:g}",
            "warning",
            {"technical": technical, "fund_flow": fund_flow},
            {"technical": cfg.technical_gte, "fund_flow": cfg.fund_flow_lt},
            message,
        )


def _add_sentiment_risk(
    value: float | None,
    cfg: SystemicRiskConfig,
    red_flags: list[str],
    warnings: list[str],
    offsets: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    # Step 2: sentiment_red 配置为不可达上界(默认 200)，情绪极端只落 warning 观察，
    # 保留触发记录但不参与红旗表决（8.9.1：sentiment>=80 后 fwd20 +2.44% 方向存疑）。
    if value is not None and value >= cfg.sentiment_red:
        message = f"情绪面 {_temperature_text(value)} 进入高温，交易拥挤风险上升。"
        red_flags.append(message)
        _add_rule(
            triggered_rules,
            f"sentiment_gte_{cfg.sentiment_red:g}",
            "red_flag",
            value,
            cfg.sentiment_red,
            message,
        )
    elif value is not None and value >= cfg.sentiment_warning:
        message = f"情绪面 {_temperature_text(value)} 偏热（观察，不作为红旗）。"
        warnings.append(message)
        _add_rule(
            triggered_rules,
            f"sentiment_gte_{cfg.sentiment_warning:g}",
            "warning",
            value,
            cfg.sentiment_warning,
            message,
        )
    elif value is not None and value < cfg.sentiment_offset_below:
        message = f"情绪面 {_temperature_text(value)} 未明显过热。"
        offsets.append(message)
        _add_rule(
            triggered_rules,
            f"sentiment_lt_{cfg.sentiment_offset_below:g}",
            "offset",
            value,
            cfg.sentiment_offset_below,
            message,
        )


def _add_macro_risk(
    value: float | None,
    domestic_value: float | None,
    cfg: SystemicRiskConfig,
    warnings: list[str],
    offsets: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    # Step 2: 原 macro_liquidity_lt_40 红旗下限 988 天零触发（国内口径 min=46.1），
    # 去红旗；改为国内口径偏紧(<50)告警，>=50 为缓释。
    effective = domestic_value if domestic_value is not None else value
    if effective is None:
        return
    calibre = "国内口径 " if domestic_value is not None else ""
    if effective < cfg.macro_domestic_warning_below:
        message = (
            f"宏观流动性{calibre}{_temperature_text(effective)} 偏紧，对估值形成压力（观察）。"
        )
        warnings.append(message)
        _add_rule(
            triggered_rules,
            f"macro_liquidity_lt_{cfg.macro_domestic_warning_below:g}",
            "warning",
            effective,
            cfg.macro_domestic_warning_below,
            message,
        )
    elif effective >= 50:
        message = f"宏观流动性{calibre}{_temperature_text(effective)} 未构成主要压力。"
        offsets.append(message)
        _add_rule(triggered_rules, "macro_liquidity_gte_50", "offset", effective, 50, message)


def _add_fundamental_risk(
    value: float | None,
    cfg: SystemicRiskConfig,
    warnings: list[str],
    offsets: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    if value is not None and value >= cfg.fundamental_offset_gte:
        message = f"基本面 {_temperature_text(value)} 对风险偏好有一定支撑。"
        offsets.append(message)
        _add_rule(
            triggered_rules,
            f"fundamental_gte_{cfg.fundamental_offset_gte:g}",
            "offset",
            value,
            cfg.fundamental_offset_gte,
            message,
        )
    elif value is not None and value < cfg.fundamental_warning_below:
        message = f"基本面 {_temperature_text(value)} 偏弱。"
        warnings.append(message)
        _add_rule(
            triggered_rules,
            f"fundamental_lt_{cfg.fundamental_warning_below:g}",
            "warning",
            value,
            cfg.fundamental_warning_below,
            message,
        )


def _add_composite_risk(
    value: float | None,
    cfg: SystemicRiskConfig,
    red_flags: list[str],
    warnings: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    # Step 2: 原 composite_gte_80 死规则（峰值 68.6）→ 红旗收敛到 65（与高温极端一致）。
    if value is not None and value >= cfg.composite_red:
        message = f"综合温度 {_temperature_text(value)} 进入高温区。"
        red_flags.append(message)
        _add_rule(
            triggered_rules,
            f"composite_gte_{cfg.composite_red:g}",
            "red_flag",
            value,
            cfg.composite_red,
            message,
        )
    elif value is not None and value >= cfg.composite_warning:
        message = f"综合温度 {_temperature_text(value)} 处于偏热区。"
        warnings.append(message)
        _add_rule(
            triggered_rules,
            f"composite_gte_{cfg.composite_warning:g}",
            "warning",
            value,
            cfg.composite_warning,
            message,
        )


def _add_divergence_risk(
    fast: float | None,
    slow: float | None,
    divergence: float | None,
    cfg: SystemicRiskConfig,
    red_flags: list[str],
    offsets: list[str],
    triggered_rules: list[dict[str, Any]],
) -> None:
    """快慢背离风控：深度背离且短线偏热 -> 派发红旗；深度背离且短线冰点 -> 底部缓冲。"""
    if fast is None or slow is None or divergence is None:
        return
    if divergence >= cfg.divergence_extreme and fast >= cfg.divergence_hot_fast:
        message = (
            f"快慢深度背离且短线偏热（快 {_temperature_text(fast)}，慢 {_temperature_text(slow)}），"
            "短线资金情绪与慢变量脱节，派发警惕窗口。"
        )
        red_flags.append(message)
        _add_rule(
            triggered_rules,
            "divergence_extreme_hot_fast",
            "red_flag",
            {"divergence": divergence, "fast": fast, "slow": slow},
            {"divergence": cfg.divergence_extreme, "fast": cfg.divergence_hot_fast},
            message,
        )
    elif divergence <= -cfg.divergence_extreme and fast <= cfg.divergence_ice_fast:
        message = (
            f"快慢深度背离且短线冰点（快 {_temperature_text(fast)}，慢 {_temperature_text(slow)}），"
            "情绪资金处于冰点而慢变量温和，底部反攻窗口观察。"
        )
        offsets.append(message)
        _add_rule(
            triggered_rules,
            "divergence_extreme_cold_fast",
            "offset",
            {"divergence": divergence, "fast": fast, "slow": slow},
            {"divergence": -cfg.divergence_extreme, "fast": cfg.divergence_ice_fast},
            message,
        )


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
            "多项温度读数污染信号同时出现，读数可信度低，应优先控制回撤和仓位暴露。",
        )
    if red_flags and warnings:
        return (
            "中等偏高",
            "elevated_systemic_risk",
            "存在明确读数污染源，但尚未形成全面污染。",
        )
    if red_flags or len(warnings) >= 2:
        return (
            "中等",
            "moderate_systemic_risk",
            "读数可信度可控但不低，需要观察资金、情绪和宽度是否继续恶化。",
        )
    return (
        "低到中等",
        "contained_systemic_risk",
        "当前没有明显读数污染共振，更多的是结构性机会和结构性风险。",
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
