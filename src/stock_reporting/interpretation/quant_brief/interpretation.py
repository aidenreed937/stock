"""量化投研简报的四步决策解释。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_reporting.interpretation.quant_brief.config import (
    QuantBriefConfig,
)
from stock_reporting.interpretation.quant_brief.helpers import (
    _as_float,
    _breadth,
    _comparison_as_of,
    _composite_delta,
    _composite_temperature,
    _crowding_temperature,
    _dimension_temperatures,
    _fact_observation,
    _fund_flow_confirmed,
    _gte,
    _mapping,
    _panel_rows,
    _priority_excluded_rows,
    _sector_item,
    _temperature_band,
    _value_text,
)
from stock_reporting.interpretation.quant_brief.risk_gates import (
    evaluate_breadth_gate as _evaluate_breadth_gate,
)
from stock_reporting.interpretation.quant_brief.risk_gates import (
    evaluate_funding_health as _evaluate_funding_health,
)
from stock_reporting.interpretation.quant_brief.risk_gates import evaluate_risk_gates
from stock_reporting.interpretation.quant_brief.risk_gates import (
    evaluate_systemic_gate as _evaluate_systemic_gate,
)
from stock_reporting.interpretation.quant_brief.veto import evaluate_veto


def evaluate_macro(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
) -> dict[str, Any]:
    """根据综合温度和系统风险生成宏观定基调结论。"""
    composite = _composite_temperature(market_scores)
    risk = _mapping(market_scores.get("systemic_risk"))
    if composite is None:
        risk_gate = _evaluate_systemic_gate(config, market_scores)
        if risk_gate.get("severity") == "hard":
            return {
                "status": "partial",
                "temperature": None,
                "band_id": "high_risk",
                "band_label": config.temperature_bands[-1].label,
                "equity_position_band": config.defensive_position_band,
                "stance": "估值红旗或系统性风险已触发，权益仓位以防守为主；综合温度缺失。",
                "tactic": "执行防守仓位上限，先补齐综合温度事实后再恢复进攻判断。",
                "risk_level": str(risk.get("level") or "不可判定"),
                "risk_status": str(risk.get("status") or "insufficient"),
                "reasons": [
                    "综合温度没有可用值。",
                    str(risk_gate.get("message") or "系统性风险闸门已触发。"),
                ],
                "risk_gate": risk_gate,
            }
        return {
            "status": "insufficient",
            "temperature": None,
            "band_id": "insufficient",
            "band_label": "不可判定",
            "equity_position_band": "不可判定",
            "stance": "综合温度缺失，暂不设定仓位档位。",
            "tactic": "先补齐市场温度事实，再进行仓位决策。",
            "risk_level": str(risk.get("level") or "不可判定"),
            "risk_status": str(risk.get("status") or "insufficient"),
            "reasons": ["综合温度没有可用值。"],
            "risk_gate": risk_gate,
        }

    dimensions = _dimension_temperatures(market_scores)
    valuation = dimensions.get("valuation")
    risk_gate = _evaluate_systemic_gate(config, market_scores)
    defensive_override = risk.get("status") == "high_systemic_risk" or (
        valuation is not None and valuation >= config.valuation_red_flag_temperature
    )
    band = _temperature_band(config, composite)
    if defensive_override:
        band = config.temperature_bands[-1]
    reasons = [
        f"综合温度 {_value_text(composite)}，落在“{band.label}”。",
        f"系统风险等级为 {risk.get('level', '不可判定')}。",
    ]
    for key in ("message",):
        if risk.get(key):
            reasons.append(str(risk[key]))
    if defensive_override:
        reasons.append("估值红旗或系统性风险已触发，仓位执行应优先服从防守上限。")
    position_band = (
        config.defensive_position_band if defensive_override else band.equity_position_band
    )
    stance = (
        "估值红旗或系统性风险已触发，权益仓位以防守为主。" if defensive_override else band.stance
    )
    tactic = (
        "降低总仓位上限，停止加杠杆和高拥挤追高，等待风险信号消退。"
        if defensive_override
        else (
            "只减不加，等待综合温度回落或宽度与资金形成确认。"
            if composite >= config.composite_red_flag_temperature
            else band.tactic
        )
    )
    if composite >= config.composite_red_flag_temperature and not defensive_override:
        stance = "综合温度进入只减不加区间，风险收益比开始恶化。"
    return {
        "status": "ready",
        "temperature": composite,
        "band_id": band.band_id,
        "band_label": band.label,
        "equity_position_band": position_band,
        "stance": stance,
        "tactic": tactic,
        "risk_level": str(risk.get("level") or "不可判定"),
        "risk_status": str(risk.get("status") or "insufficient"),
        "reasons": reasons,
        "risk_gate": risk_gate,
    }


def evaluate_nature(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    market_facts: pl.DataFrame | None,
) -> dict[str, Any]:
    """根据快慢变量、行业扩散和跨期变化判断行情性质。"""
    dimensions = _dimension_temperatures(market_scores)
    technical = dimensions.get("technical")
    fund_flow = dimensions.get("fund_flow")
    breadth = _breadth(industry_scores)
    funding_health = _evaluate_funding_health(config, market_facts)
    breadth_gate = _evaluate_breadth_gate(config, market_scores, industry_scores, market_facts)
    top5 = _fact_observation(market_facts, "amount_top_5pct_share")
    top5_value = _as_float(top5.get("value_float")) if top5 else None
    delta, comparison_status = _composite_delta(market_scores)
    positive_20d_count = breadth["positive_20d_count"]
    positive_60d_count = breadth["positive_60d_count"]

    missing: list[str] = []
    if technical is None:
        missing.append("technical")
    if fund_flow is None:
        missing.append("fund_flow")
    if positive_20d_count is None:
        missing.append("positive_return_20d_count")
    if positive_60d_count is None:
        missing.append("positive_return_60d_count")

    if (
        top5_value is not None
        and top5_value > config.top5pct_share
        and _gte(dimensions.get("valuation"), config.high_heat_valuation)
        and _gte(dimensions.get("sentiment"), config.high_heat_sentiment)
    ):
        nature_type = "high_heat_divergence"
        message = "Top5% 成交集中度、估值和情绪同时偏热，属于高位极热背离，先执行风险约束。"
    elif (
        not missing
        and fund_flow is not None
        and fund_flow >= config.true_bull_min_fund_flow
        and _gte(positive_60d_count, config.true_bull_min_positive_60d_count)
        and delta is not None
        and delta >= config.true_bull_min_composite_delta
        and breadth_gate["status"] == "clear"
        and not funding_health["hard_stop"]
    ):
        nature_type = "true_bull_resonance"
        message = "资金、60日行业扩散和综合温度同步改善，满足三维共振的配置条件。"
    elif (
        not missing
        and technical is not None
        and technical >= config.pulse_min_technical
        and fund_flow is not None
        and fund_flow < config.pulse_max_fund_flow
        and _gte(positive_20d_count, config.pulse_min_positive_20d_count)
        and positive_60d_count is not None
        and positive_60d_count <= config.pulse_max_positive_60d_count
    ):
        nature_type = "stock_pulse_short_strong_medium_weak"
        message = "技术和20日扩散偏强，但资金及60日扩散不足，更像存量脉冲而非中期趋势反转。"
    elif missing:
        nature_type = "insufficient_data"
        message = "快慢变量或行业扩散事实不足，暂不能严谨判断行情性质。"
    else:
        nature_type = "neutral_or_mixed"
        message = "当前快慢变量没有满足配置规则的单一性质标签，按中性或混合状态观察。"

    if funding_health["hard_stop"]:
        nature_type = "distribution_risk"
        message = "资金与成交结构出现高风险背离观察，暂停进攻并等待后续事实确认。"
    elif funding_health["flags"]:
        message += " 主力资金或杠杆健康度出现观察信号，不能仅凭指数上涨确认行情质量。"
    if breadth_gate["status"] == "watch":
        message += " 市场宽度未形成全面确认，需防范少数抱团掩护式上涨。"
    if comparison_status == "insufficient_comparison":
        message += " 综合温度缺少有效对比值，真牛市判定不能仅凭当前截面确认。"
    nature_label = (
        "资金-成交背离风险（硬闸门观察）" if nature_type == "distribution_risk" else nature_type
    )
    return {
        "status": "ready" if not missing else "partial",
        "nature_type": nature_type,
        "nature_label": nature_label,
        "message": message,
        "technical_temperature": technical,
        "fund_flow_temperature": fund_flow,
        "breadth_20d": breadth["positive_20d_count"],
        "breadth_60d": breadth["positive_60d_count"],
        "breadth_20d_share": breadth["positive_20d_share"],
        "breadth_60d_share": breadth["positive_60d_share"],
        "scored_industry_count": breadth["scored_industry_count"],
        "composite_delta": delta,
        "comparison_status": comparison_status,
        "comparison_as_of": _comparison_as_of(market_scores),
        "missing": missing,
        "funding_health": funding_health,
        "breadth_gate": breadth_gate,
    }


def evaluate_sector(
    config: QuantBriefConfig,
    industry_panel: pl.DataFrame,
) -> dict[str, Any]:
    """从行业面板筛选优先、回避和落后方向。"""
    rows = _panel_rows(industry_panel)
    priority: list[dict[str, Any]] = []
    avoid: list[dict[str, Any]] = []
    valid_rows = [row for row in rows if row.get("status") == "ok"]
    for row in rows:
        if row.get("status") != "ok":
            continue
        tags = str(row.get("tags") or "")
        crowding = _crowding_temperature(row)
        structure = _as_float(row.get("structure_score"))
        if (
            structure is not None
            and structure >= config.min_priority_structure_score
            and (crowding is None or crowding < config.crowding_temperature)
            and ((_as_float(row.get("tcr")) or 0.0) < config.industry_tcr_warning)
            and "景气承压" not in tags
            and "拥挤风险" not in tags
            and (not config.require_fund_flow_confirmation or _fund_flow_confirmed(row))
        ):
            priority.append(
                _sector_item(
                    row,
                    source_group="priority",
                    reason="结构分靠前、未进入高拥挤，且资金确认条件满足。",
                )
            )
        if (
            (crowding is not None and crowding >= config.crowding_temperature)
            or (_as_float(row.get("tcr")) or 0.0) >= config.industry_tcr_warning
            or "拥挤风险" in tags
            or "景气承压" in tags
        ):
            reason = "拥挤温度偏高，或行业基本面标签显示景气承压。"
            avoid.append(_sector_item(row, source_group="avoid", reason=reason))

    priority.sort(key=lambda item: _as_float(item.get("structure_score")) or -1, reverse=True)
    selected_priority = priority[: config.max_priority_industries]
    priority_excluded = _priority_excluded_rows(valid_rows, selected_priority, config)
    avoid.sort(
        key=lambda item: (
            _as_float(item.get("crowding_temperature")) or -1,
            _as_float(item.get("structure_score")) or -1,
        ),
        reverse=True,
    )
    valid_rows.sort(key=lambda row: _as_float(row.get("structure_score")) or 101)
    lagging = [
        _sector_item(row, source_group="lagging", reason="结构分靠后，用于排查弱势暴露。")
        for row in valid_rows[: config.max_lagging_industries]
    ]
    return {
        "priority": selected_priority,
        "priority_excluded": priority_excluded,
        "avoid": avoid[: config.max_avoid_industries],
        "lagging": lagging,
        "selection_rule": "优先方向要求结构分达标、不拥挤、不景气承压，并按配置要求检查资金确认。",
    }


def evaluate_data_quality_notes(
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    veto: dict[str, Any],
    risk_gates: dict[str, Any] | None = None,
) -> list[str]:
    """生成数据质量和时效限制。"""
    notes = [
        "Top5% 成交占比是最新成交日的横截面事实，不是20日均值，不能单独解释为趋势。",
        "行业 TCR 原值是成交额占比/百分点，拥挤判断使用其历史分位温度。",
        "主力资金使用 moneyflow 大单分类作为可观测代理，不等同于真实机构账户或 Level-2 机构席位。",
        "两融20日/60日增速只代表当前可用事实；当前链路没有连续状态序列，不能严谨确认高位拐点。",
        "外盘风险只作宏观背景，不直接改变五档仓位档位。",
    ]
    missing = veto.get("missing")
    if isinstance(missing, list) and missing:
        notes.append(f"以下排雷事实缺失或样本不足: {'、'.join(str(item) for item in missing)}。")
    if isinstance(risk_gates, dict):
        insufficient_gates = [
            str(gate.get("title"))
            for gate in risk_gates.get("gates", [])
            if isinstance(gate, dict) and gate.get("status") == "insufficient"
        ]
        if insufficient_gates:
            notes.append(f"以下风控闸门资料不足，仅作部分观察: {'、'.join(insufficient_gates)}。")
    freshness = market_scores.get("data_freshness")
    if isinstance(freshness, dict) and freshness.get("stale_metric_count"):
        notes.append(
            f"市场温度存在 {freshness['stale_metric_count']} 个超过新鲜度阈值的指标，评分已按配置降权。"
        )
    status_counts = industry_scores.get("fundamental_status_counts")
    if isinstance(status_counts, dict) and status_counts.get("stale_blended"):
        notes.append("行业正式财报存在滞后，行业基本面部分使用快速确认项提高权重。")
    return notes


def evaluate_reading_notes(
    macro: dict[str, Any],
    nature: dict[str, Any],
    veto: dict[str, Any],
    sector: dict[str, Any],
    risk_gates: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """按已验证事实和机制推断分层生成阅读说明。"""
    verified = []
    if macro.get("temperature") is not None:
        verified.append(
            f"综合温度为 {_value_text(macro['temperature'])}，档位为 {macro['band_label']}。"
        )
    if nature.get("breadth_20d") is not None and nature.get("breadth_60d") is not None:
        verified.append(
            f"行业上涨扩散为20日 {nature['breadth_20d']} 家、60日 {nature['breadth_60d']} 家。"
        )
    if nature.get("composite_delta") is not None:
        verified.append(f"综合温度相对对比日变化 {nature['composite_delta']:+.2f}。")
    top5 = veto.get("top5pct", {})
    if top5.get("value") is not None:
        verified.append(f"最新成交日 Top5% 成交占比为 {_value_text(top5['value'] * 100)}%。")
    funding = nature.get("funding_health", {})
    if isinstance(funding, dict):
        flow = _as_float(funding.get("main_large_order_net_inflow_share"))
        if flow is not None:
            source = funding.get("main_large_order_net_inflow_share_source")
            label = (
                "主力大单" if source == "main_large_order_net_inflow_share" else "主力净流入代理"
            )
            verified.append(f"最新资金事实：{label}净流入成交占比 {flow:+.2%}。")
        growth = _as_float(funding.get("margin_balance_growth_20d"))
        if growth is not None:
            verified.append(f"两融余额20日增速为 {growth:+.2%}。")
    inference = [str(nature.get("message") or "行情性质暂无明确标签。")]
    if macro.get("tactic"):
        inference.append(str(macro["tactic"]))
    if isinstance(funding, dict) and funding.get("flags"):
        inference.append(
            "资金与杠杆信号用于风险确认；当前事实不足以单独确认连续出货或严格去杠杆拐点。"
        )
    if isinstance(risk_gates, dict) and risk_gates.get("status") == "partial":
        inference.append("部分风控闸门资料不足，仓位结论应服从可验证事实，不用缺失数据补齐叙事。")
    if sector.get("priority"):
        inference.append("行业方向只在完成市场风险排查后使用，优先方向不等同于个股买入建议。")
    return {"verified_facts": verified, "mechanism_inferences": inference}


__all__ = [
    "evaluate_data_quality_notes",
    "evaluate_macro",
    "evaluate_nature",
    "evaluate_reading_notes",
    "evaluate_risk_gates",
    "evaluate_sector",
    "evaluate_veto",
]
