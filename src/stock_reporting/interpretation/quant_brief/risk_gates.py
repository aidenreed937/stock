"""量化投研简报的四道风控闸门。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_reporting.interpretation.quant_brief.config import QuantBriefConfig
from stock_reporting.interpretation.quant_brief.helpers import (
    _as_float,
    _breadth,
    _crowding_temperature,
    _dimension_temperatures,
    _fact_observation,
    _funding_observation,
    _mapping,
    _panel_rows,
    _value_text,
)


def evaluate_risk_gates(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    industry_panel: pl.DataFrame,
    market_facts: pl.DataFrame | None,
) -> dict[str, Any]:
    """执行宏观、资金杠杆、宽度和行业拥挤四道风控闸门。"""
    gates = [
        evaluate_systemic_gate(config, market_scores),
        _evaluate_funding_gate(config, market_facts),
        evaluate_breadth_gate(config, market_scores, industry_scores, market_facts),
        evaluate_industry_gate(config, industry_panel),
    ]
    hard_stop = any(gate["severity"] == "hard" for gate in gates)
    has_watch = any(gate["status"] in {"watch", "triggered"} for gate in gates)
    has_insufficient = any(gate["status"] == "insufficient" for gate in gates)
    status = "blocked" if hard_stop else ("watch" if has_watch else "clear")
    if has_insufficient and status == "clear":
        status = "partial"
    return {
        "status": status,
        "hard_stop": hard_stop,
        "max_position_band": config.defensive_position_band if hard_stop else None,
        "summary": (
            "至少一道总风险闸门触发，停止进攻并执行防守上限。"
            if hard_stop
            else (
                "存在需要观察的风险闸门，按宏观仓位档位控制，不追高。"
                if has_watch
                else "四道风控闸门暂未触发硬性风险信号。"
            )
        ),
        "gates": gates,
    }


def evaluate_systemic_gate(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
) -> dict[str, str]:
    """评估估值红旗、综合温度和上游系统性风险。"""
    dimensions = _dimension_temperatures(market_scores)
    valuation = dimensions.get("valuation")
    composite = _composite_temperature(market_scores)
    risk = _mapping(market_scores.get("systemic_risk"))
    flags: list[str] = []
    hard = False
    if risk.get("status") == "high_systemic_risk":
        flags.append("系统性风险状态已达高风险")
        hard = True
    if valuation is not None and valuation >= config.valuation_red_flag_temperature:
        flags.append(f"估值温度 {valuation:.2f} 达到红旗阈值")
        hard = True
    elif valuation is not None and valuation >= 80:
        flags.append(f"估值温度 {valuation:.2f} 已进入高温观察区")
    if composite is not None and composite >= config.composite_red_flag_temperature:
        flags.append(f"综合温度 {composite:.2f} 达到只减不加阈值")
    has_risk_fact = any(risk.get(key) is not None for key in ("status", "level", "message"))
    if not flags and valuation is None and composite is None and not has_risk_fact:
        return _gate(
            "systemic_valuation",
            "系统性风险与估值红旗",
            "insufficient",
            "none",
            "缺少估值、综合温度和系统风险事实。",
            "补齐市场温度事实后再设定总仓位上限。",
            "-",
        )
    status = "triggered" if hard else ("watch" if flags else "clear")
    severity = "hard" if hard else ("watch" if flags else "none")
    action = (
        "执行防守仓位上限，停止加杠杆和高拥挤追高。"
        if hard
        else ("只减不加，等待估值和风险信号回落。" if flags else "可进入第二道资金与杠杆检查。")
    )
    return _gate(
        "systemic_valuation",
        "系统性风险与估值红旗",
        status,
        severity,
        "；".join(flags) if flags else "估值和系统风险未触发当前配置阈值。",
        action,
        f"估值温度 {_value_text(valuation)}；综合温度 {_value_text(composite)}；系统风险 {risk.get('level', '-')}。",
    )


def evaluate_breadth_gate(
    config: QuantBriefConfig,
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    market_facts: pl.DataFrame | None,
) -> dict[str, str]:
    """评估站上 60 日线占比和 20 日行业扩散。"""
    breadth = _breadth(industry_scores)
    above_ma60_row = _fact_observation(market_facts, "above_ma60_share")
    above_ma60 = _as_float(above_ma60_row.get("value_float")) if above_ma60_row else None
    positive20 = breadth["positive_20d_count"]
    missing = above_ma60 is None or positive20 is None
    weak_reasons: list[str] = []
    if above_ma60 is not None and above_ma60 < config.breadth_above_ma60_weak:
        weak_reasons.append(
            f"站上60日线占比 {above_ma60:.2%} 低于 {config.breadth_above_ma60_weak:.0%}"
        )
    if positive20 is not None and positive20 < config.positive_20d_sector_min:
        weak_reasons.append(f"20日上涨行业 {positive20} 家少于 {config.positive_20d_sector_min} 家")
    if missing and not weak_reasons:
        status, severity = "insufficient", "none"
        message = "站上60日线占比或20日行业扩散事实不足。"
        action = "补齐宽度事实后再判断全面行情与抱团行情。"
    elif weak_reasons:
        status, severity = "watch", "watch"
        message = "；".join(weak_reasons)
        action = "停止追高非主线个股，优先等待中期宽度修复。"
    elif (
        above_ma60 is not None
        and positive20 is not None
        and above_ma60 >= config.breadth_above_ma60_healthy
        and positive20 >= config.positive_20d_sector_min
    ):
        status, severity = "clear", "none"
        message = "中期均线宽度和20日行业扩散均达到健康观察线。"
        action = "可进入行业拥挤度检查，仍需结合资金确认。"
    else:
        status, severity = "watch", "watch"
        message = "宽度尚未达到健康确认线，行情质量仍需观察。"
        action = "控制追高，等待站上60日线占比和行业扩散同步改善。"
    return _gate(
        "market_breadth",
        "全市场技术宽度",
        status,
        severity,
        message,
        action,
        f"站上60日线占比 {_value_text(above_ma60 * 100 if above_ma60 is not None else None)}%；"
        f"20日上涨行业 {positive20 if positive20 is not None else '-'} 家；"
        f"技术温度 {_value_text(_dimension_temperatures(market_scores).get('technical'))}。",
    )


def evaluate_industry_gate(
    config: QuantBriefConfig,
    industry_panel: pl.DataFrame,
) -> dict[str, str]:
    """评估行业 TCR 与拥挤温度；高风险只作用于局部方向。"""
    rows = [row for row in _panel_rows(industry_panel) if row.get("status") == "ok"]
    risk_rows = [
        row
        for row in rows
        if _as_float(row.get("tcr")) is not None or _crowding_temperature(row) is not None
    ]
    risk_rows.sort(key=lambda row: _as_float(row.get("tcr")) or -1, reverse=True)
    hard_rows = [
        row
        for row in risk_rows
        if (_as_float(row.get("tcr")) or 0) >= config.industry_tcr_hard
        or (_crowding_temperature(row) or 0) >= config.industry_crowding_hard_temperature
    ]
    watch_rows = [
        row
        for row in risk_rows
        if (_as_float(row.get("tcr")) or 0) >= config.industry_tcr_warning
        or (_crowding_temperature(row) or 0) >= config.crowding_temperature
    ]
    if not risk_rows:
        return _gate(
            "industry_crowding",
            "行业拥挤度与成交占比",
            "insufficient",
            "none",
            "行业 TCR 或拥挤温度事实不足。",
            "补齐行业面板后再决定回避方向。",
            "暂无行业 TCR 可用值。",
        )
    names = "、".join(
        str(row.get("industry_name") or row.get("industry_code")) for row in watch_rows[:5]
    )
    if hard_rows:
        status, severity = "triggered", "local"
        message = f"存在原始 TCR ≥ {config.industry_tcr_hard:.0f}% 或拥挤温度 ≥ {config.industry_crowding_hard_temperature:.0f} 的行业。"
        action = "局部方向坚决回避，不因行业强势或基本面叙事追高。"
    elif watch_rows:
        status, severity = "watch", "watch"
        message = f"有行业进入 TCR ≥ {config.industry_tcr_warning:.0f}% 或拥挤温度观察区。"
        action = "从候选方向剔除高拥挤行业，等待拥挤度回落。"
    else:
        status, severity = "clear", "none"
        message = "行业 TCR 和拥挤温度未触发当前配置阈值。"
        action = "保留结构分靠前且资金确认的方向。"
    return _gate(
        "industry_crowding",
        "行业拥挤度与成交占比",
        status,
        severity,
        message,
        action,
        f"最高观察行业 {names or '-'}；最高 TCR {_value_text(_as_float(risk_rows[0].get('tcr')))}%。",
    )


def evaluate_funding_health(
    config: QuantBriefConfig,
    market_facts: pl.DataFrame | None,
) -> dict[str, Any]:
    """读取并解释主力资金、成交放量和两融健康度。"""
    observation = _funding_observation(market_facts)
    main_flow = _as_float(observation.get("main_large_order_net_inflow_share"))
    main_flow_source = str(observation.get("main_large_order_net_inflow_share_source") or "unknown")
    cumulative_flow = _as_float(observation.get("main_money_net_inflow_share_20d_cum"))
    market_amount_pct = _as_float(observation.get("market_amount_percentile_1250d"))
    margin_buy = _as_float(observation.get("margin_buy_share"))
    margin_growth20 = _as_float(observation.get("margin_balance_growth_20d"))
    margin_pen_pct = _as_float(observation.get("margin_penetration_percentile_1250d"))
    missing = [
        name
        for name, value in (
            ("main_large_order_net_inflow_share", main_flow),
            ("main_money_net_inflow_share_20d_cum", cumulative_flow),
            ("market_amount_percentile_1250d", market_amount_pct),
            ("margin_buy_share", margin_buy),
            ("margin_balance_growth_20d", margin_growth20),
            ("margin_penetration_percentile_1250d", margin_pen_pct),
        )
        if value is None
    ]
    flags: list[str] = []
    hard_stop = False
    flow_label = (
        "主力大单（大单+超大单）"
        if main_flow_source == "main_large_order_net_inflow_share"
        else "主力净流入（moneyflow 分类代理）"
    )
    if main_flow is not None and main_flow <= config.main_money_outflow_share_hard:
        if (
            market_amount_pct is not None
            and market_amount_pct >= config.market_amount_high_percentile
        ):
            flags.append(
                f"{flow_label}净流入占比 {main_flow:.2%} 且成交额处于{market_amount_pct:.1f}分位，触发高风险观察"
            )
            hard_stop = main_flow_source == "main_large_order_net_inflow_share"
        else:
            flags.append(f"{flow_label}净流入占比 {main_flow:.2%} 低于出货观察线")
    if cumulative_flow is not None and cumulative_flow < 0:
        flags.append(f"主力净流入20日累计成交占比 {cumulative_flow:.2%} 为负")
    if margin_buy is not None and margin_buy > config.margin_buy_share_warning:
        flags.append(f"融资买入占比 {margin_buy:.2%} 高于过热观察线")
    if (
        margin_pen_pct is not None
        and margin_pen_pct >= config.margin_penetration_extreme_percentile
    ):
        if margin_growth20 is not None and margin_growth20 < 0:
            flags.append(
                f"两融渗透率处于{margin_pen_pct:.1f}分位且20日余额增速 {margin_growth20:.2%} 为负，去杠杆风险需观察"
            )
        else:
            flags.append(f"两融渗透率处于{margin_pen_pct:.1f}分位，杠杆水位偏高")
    if not flags and not missing:
        status = "clear"
    elif hard_stop or flags:
        status = "watch"
    else:
        status = "insufficient"
    if hard_stop:
        action = "停止进攻，等待主力资金和成交结构重新确认。"
    elif flags:
        action = "资金与杠杆只作风险确认，暂不据此宣称拐点；降低追高和杠杆暴露。"
    else:
        action = "主力资金和杠杆未触发当前观察线，仍需结合宽度确认。"
    source_note = (
        "精确大单字段可用，主力大单口径为大单与超大单分类合计。"
        if main_flow_source == "main_large_order_net_inflow_share"
        else "精确大单字段缺失，当前回退为 moneyflow 主力净流入分类代理。"
    )
    return {
        **observation,
        "status": status,
        "status_label": {"clear": "健康观察", "watch": "风险观察", "insufficient": "资料不足"}[
            status
        ],
        "hard_stop": hard_stop,
        "flags": flags,
        "missing": missing,
        "message": "；".join(flags) if flags else "主力资金与杠杆未触发当前配置阈值。",
        "action": action,
        "facts_text": (
            f"{flow_label}净流入占比 {_value_text(main_flow * 100 if main_flow is not None else None)}%；"
            f"20日累计 {_value_text(cumulative_flow * 100 if cumulative_flow is not None else None)}%；"
            f"融资买入占比 {_value_text(margin_buy * 100 if margin_buy is not None else None)}%；"
            f"两融20日增速 {_value_text(margin_growth20 * 100 if margin_growth20 is not None else None)}%；"
            f"两融渗透率分位 {_value_text(margin_pen_pct)}。"
        ),
        "note": (
            f"{source_note} 主力资金使用 Tushare moneyflow 分类，不等同于机构账户；"
            "单日事实不能单独确认连续出货或杠杆拐点。"
        ),
    }


def _evaluate_funding_gate(
    config: QuantBriefConfig,
    market_facts: pl.DataFrame | None,
) -> dict[str, str]:
    health = evaluate_funding_health(config, market_facts)
    status = health["status"]
    severity = "hard" if health["hard_stop"] else ("watch" if status == "watch" else "none")
    return _gate(
        "funding_leverage",
        "主力资金与杠杆健康度",
        "triggered" if health["hard_stop"] else status,
        severity,
        health["message"],
        health["action"],
        health["facts_text"],
    )


def _gate(
    gate_id: str,
    title: str,
    status: str,
    severity: str,
    message: str,
    action: str,
    facts_text: str,
) -> dict[str, str]:
    labels = {"triggered": "触发", "watch": "观察", "clear": "通过", "insufficient": "资料不足"}
    return {
        "id": gate_id,
        "title": title,
        "status": status,
        "status_label": labels.get(status, status),
        "severity": severity,
        "message": message,
        "action": action,
        "facts_text": facts_text,
    }


def _composite_temperature(scores: dict[str, Any]) -> float | None:
    composite = scores.get("composite")
    return _as_float(composite.get("temperature")) if isinstance(composite, dict) else None


__all__ = [
    "evaluate_breadth_gate",
    "evaluate_funding_health",
    "evaluate_industry_gate",
    "evaluate_risk_gates",
    "evaluate_systemic_gate",
]
