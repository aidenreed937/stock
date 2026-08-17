"""普通投资者简报业务研判与决策逻辑。

本模块属于 Analytics 领域层，负责将市场温度评分、行业结构面板与健康度
转化为面向普通投资者的参与建议、选定观察方向、拥挤风险行业提示及阅读指引。
展现层 (Reporting) 仅消费本模块生成的结构化分析结果。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl


def evaluate_participation_decision(
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    dimensions: dict[str, float | None],
) -> dict[str, Any]:
    """生成普通投资者参与决策与操作指引。"""
    risk = market_scores.get("systemic_risk", {})
    if not isinstance(risk, dict):
        risk = {}
    composite = _composite_temperature(market_scores)
    risk_status = str(risk.get("status") or "")
    risk_level = str(risk.get("level") or "不可判定")
    health = industry_scores.get("structure_health", {})
    health_status = str(health.get("status") or "") if isinstance(health, dict) else ""

    stance = "可以参与，但只按结构性机会处理"
    action = "控制仓位和追高节奏，优先观察结构分靠前且不拥挤的行业。"
    if risk_status == "high_systemic_risk" or _gte(composite, 80):
        stance = "系统风险偏高，普通投资者以防守和等待为主"
        action = "不宜追高扩仓，先控制回撤，再等待风险信号降温。"
    elif risk_status == "elevated_systemic_risk":
        stance = "可以小心参与，但不是全面进攻环境"
        action = "只按结构性方向观察，避免估值高温、资金未确认或拥挤行业。"
    elif risk_status == "moderate_systemic_risk":
        stance = "可以参与，但需要分散和控制节奏"
        action = "用行业结构筛方向，等待资金和60日趋势进一步确认。"
    elif risk_status == "contained_systemic_risk":
        stance = "系统风险暂可控，可按行业结构选择方向"
        action = "仍需避开高拥挤行业，按短期和中期趋势分层参与。"

    if health_status in {"short_rebound_medium_unconfirmed", "localized_strength_weak_breadth"}:
        action += " 当前行业结构尚未形成中期全面确认，短期参与不应按趋势反转处理。"

    reasons = _decision_reasons(risk, industry_scores, dimensions, composite)
    return {
        "stance": stance,
        "action": action,
        "risk_level": risk_level,
        "risk_status": risk_status,
        "reasons": reasons,
    }


def evaluate_candidate_industries(panel: pl.DataFrame, *, limit: int) -> list[dict[str, Any]]:
    """筛选适宜观察的候选行业。"""
    rows = _panel_rows(panel)
    candidates = []
    for row in sorted(
        rows,
        key=lambda item: _as_float(item.get("structure_score")) or -1,
        reverse=True,
    ):
        tags = str(row.get("tags") or "")
        if row.get("status") != "ok":
            continue
        if (_as_float(row.get("structure_score")) or 0.0) < 50:
            continue
        if (_as_float(row.get("return_20d")) or 0.0) <= 0:
            continue
        if "拥挤风险" in tags or _gte(_as_float(row.get("crowding_temperature")), 80):
            continue
        if "景气承压" in tags:
            continue
        candidates.append(_industry_item(row, reason=_candidate_reason(row)))
        if len(candidates) >= limit:
            break
    return candidates


def evaluate_risk_industries(panel: pl.DataFrame, *, limit: int) -> list[dict[str, Any]]:
    """筛选高拥挤风险行业。"""
    rows = [
        row
        for row in _panel_rows(panel)
        if "拥挤风险" in str(row.get("tags") or "")
        or _gte(_as_float(row.get("crowding_temperature")), 80)
    ]
    rows = sorted(
        rows,
        key=lambda item: _as_float(item.get("crowding_temperature")) or -1,
        reverse=True,
    )
    return [_industry_item(row, reason=_risk_reason(row)) for row in rows[:limit]]


def evaluate_lagging_industries(panel: pl.DataFrame, *, limit: int) -> list[dict[str, Any]]:
    """筛选落后或较弱行业。"""
    rows = [
        row
        for row in _panel_rows(panel)
        if row.get("status") == "ok" and _as_float(row.get("structure_score")) is not None
    ]
    rows = sorted(rows, key=lambda item: _as_float(item.get("structure_score")) or 101)
    return [_industry_item(row, reason=_lagging_reason(row)) for row in rows[:limit]]


def evaluate_reading_notes(
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
) -> list[str]:
    """生成简报阅读要点提示。"""
    health = industry_scores.get("structure_health", {})
    pos20 = health.get("positive_return_20d_count") if isinstance(health, dict) else None
    pos60 = health.get("positive_return_60d_count") if isinstance(health, dict) else None
    total = health.get("scored_industry_count") if isinstance(health, dict) else None
    notes = [
        "第一步只看系统风险: 风险高时，行业再强也要降低追高和集中暴露。",
        "第二步看行业方向: 优先看短期配置观察，再看拥挤风险和落后方向。",
        "第三步看确认条件: 20日上涨行业多只能说明短线扩散，60日上涨行业增加才代表中期确认。",
    ]
    if pos20 is not None and pos60 is not None and total:
        notes.append(f"本期行业扩散: 20日上涨 {pos20}/{total}，60日上涨 {pos60}/{total}。")
    risk = market_scores.get("systemic_risk", {})
    if isinstance(risk, dict) and risk.get("message"):
        notes.append(f"系统风险说明: {risk['message']}")
    notes.append("本简报只使用本地产物事实，不使用新闻、政策或模型记忆补充结论。")
    return notes


def _decision_reasons(
    risk: dict[str, Any],
    industry_scores: dict[str, Any],
    dimensions: dict[str, float | None],
    composite: float | None,
) -> list[str]:
    reasons = [f"综合温度 {_value_text(composite)}，系统风险等级 {risk.get('level', '不可判定')}。"]
    red_flags = _text_items(risk.get("red_flags"))
    warnings = _text_items(risk.get("warnings"))
    offsets = _text_items(risk.get("offsets"))
    if red_flags:
        reasons.append(f"主要风险: {_join_text_items(red_flags[:2])}。")
    if warnings:
        reasons.append(f"观察信号: {_join_text_items(warnings[:2])}。")
    if offsets:
        reasons.append(f"缓冲因素: {_join_text_items(offsets[:2])}。")
    valuation = dimensions.get("valuation")
    fund_flow = dimensions.get("fund_flow")
    technical = dimensions.get("technical")
    if _gte(valuation, 80) and fund_flow is not None and fund_flow < 50:
        reasons.append("估值已经偏热，但资金面未确认；这类环境更需要控仓参与，而不是追涨。")
    if _gte(technical, 60) and fund_flow is not None and fund_flow < 50:
        reasons.append("技术修复快于资金确认，需看后续两融和主力净流入能否跟上。")
    health = industry_scores.get("structure_health", {})
    if isinstance(health, dict) and health.get("message"):
        reasons.append(f"行业结构: {health['message']}")
    return reasons


def _industry_item(row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "industry_name": row.get("industry_name") or row.get("industry_code") or "",
        "structure_score": _as_float(row.get("structure_score")),
        "structure_rank": row.get("structure_rank"),
        "return_20d": _as_float(row.get("return_20d")),
        "return_60d": _as_float(row.get("return_60d")),
        "crowding_temperature": _as_float(row.get("crowding_temperature")),
        "tcr": _as_float(row.get("tcr")),
        "tags": str(row.get("tags") or ""),
        "reason": reason,
    }


def _candidate_reason(row: dict[str, Any]) -> str:
    return_60d = _as_float(row.get("return_60d"))
    valuation = _as_float(row.get("valuation_score"))
    fundamental = _as_float(row.get("fundamental_score"))
    momentum = _as_float(row.get("momentum_score"))
    if return_60d is not None and return_60d > 0:
        return "20日和60日收益同向为正，中期确认相对更好。"
    if _gte(valuation, 70) and _gte(fundamental, 55):
        return "估值和基本面分数配合较好，可作为低估改善线索。"
    if _gte(momentum, 75):
        return "短期动量靠前，但60日趋势仍需确认。"
    return "结构分靠前且未进入高拥挤，可作为短期观察方向。"


def _risk_reason(row: dict[str, Any]) -> str:
    crowding = _as_float(row.get("crowding_temperature"))
    tcr = _as_float(row.get("tcr"))
    return f"拥挤温度 {_value_text(crowding)}，20日成交占比 {_value_text(tcr)}%，不宜追高。"


def _lagging_reason(row: dict[str, Any]) -> str:
    return "结构分靠后，短期配置性价比需要等待重新转强。"


def _composite_temperature(scores: dict[str, Any]) -> float | None:
    composite = scores.get("composite", {})
    if not isinstance(composite, dict):
        return None
    return _as_float(composite.get("temperature"))


def _panel_rows(panel: pl.DataFrame) -> list[dict[str, Any]]:
    if panel.is_empty():
        return []
    return panel.to_dicts()


def _text_items(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _join_text_items(items: list[str]) -> str:
    return "；".join(item.rstrip("。；; ") for item in items if item.strip())


def _gte(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _value_text(value: object) -> str:
    numeric = _as_float(value)
    return "-" if numeric is None else f"{numeric:.2f}"


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
