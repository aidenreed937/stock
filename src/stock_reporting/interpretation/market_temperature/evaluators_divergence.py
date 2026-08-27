"""市场温度计背离评估与特定风险段落生成。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stock_reporting.interpretation.market_temperature.bands import (
    _as_float,
    _temperature_text,
)

if TYPE_CHECKING:
    import polars as pl


def evaluate_systemic_risk_section(scores: dict[str, Any]) -> list[str]:
    """生成系统性风险模块解读行。"""
    risk = scores.get("systemic_risk", {})
    if not isinstance(risk, dict) or not risk:
        return ["- 系统性风险暂不可判定。"]
    lines = [
        f"- 风险等级: {risk.get('level', '不可判定')}",
        f"- 结论: {risk.get('message', '')}",
    ]
    red_flags = _text_items(risk.get("red_flags"))
    warnings = _text_items(risk.get("warnings"))
    offsets = _text_items(risk.get("offsets"))
    if red_flags:
        lines.append(f"- 主要风险: {_join_text_items(red_flags)}")
    if warnings:
        lines.append(f"- 观察信号: {_join_text_items(warnings)}")
    if offsets:
        lines.append(f"- 缓冲因素: {_join_text_items(offsets)}")
    return lines


def evaluate_fast_slow_section(scores: dict[str, Any]) -> list[str]:
    """生成快慢温度与背离小节（Phase 1 输出层，不改变六维合成数值）。"""
    fast_slow = scores.get("fast_slow")
    if not isinstance(fast_slow, dict) or fast_slow.get("status") != "ready":
        return []
    fast = _as_float(fast_slow.get("fast_temperature"))
    slow = _as_float(fast_slow.get("slow_temperature"))
    divergence = _as_float(fast_slow.get("divergence"))
    if fast is None or slow is None or divergence is None:
        return []
    level = str(fast_slow.get("divergence_level") or "")
    label = str(fast_slow.get("divergence_label") or "")
    level_comment = {
        "synchronized": "快慢温度同步，综合温度读数是当前市场状态的较好摘要。",
        "divergent": "快慢温度出现分歧，综合温度是快慢的中和，单看综合会掩盖结构差异；"
        "先确认是谁在驱动综合温度，再下结论。",
        "extreme": "快慢温度深度背离，综合温度只具参考意义；"
        "快冷慢温通常是情绪资金冰点 vs 基本面温，快热慢冷则为派发警惕窗口。",
    }.get(level, "")
    return [
        "## 快慢温度与背离",
        "",
        "| 快温度 | 慢温度 | 背离(快-慢) | 状态 | 读法 |",
        "|---|---:|---:|---|---|",
        f"| {_temperature_text(fast)} | {_temperature_text(slow)} | {divergence:+.2f} | {label} | {level_comment} |",
        "",
        "- 口径: 快温度 = 资金/情绪/技术 按维度权重重归一；慢温度 = 估值/基本面/宏观流动性；"
        "背离 = 快 - 慢。快慢分组不改变六维综合温度合成。",
        "",
    ]


def evaluate_key_divergences(
    dimensions: list[dict[str, Any]],
    facts: pl.DataFrame,
) -> list[str]:
    """研判各维度之间背离并生成观察建议。"""
    valuation = _dimension_temperature(dimensions, "valuation")
    fund_flow = _dimension_temperature(dimensions, "fund_flow")
    sentiment = _dimension_temperature(dimensions, "sentiment")
    technical = _dimension_temperature(dimensions, "technical")
    fundamental = _dimension_temperature(dimensions, "fundamental")
    macro = _dimension_temperature(dimensions, "macro_liquidity")
    investor_temperature = _metric_float(facts, "investor_account_temperature")
    margin_growth = _metric_float(facts, "margin_balance_growth_20d")
    main_money = _metric_float(facts, "main_money_net_inflow_share")
    lines: list[str] = []

    if technical is not None and fund_flow is not None and technical >= 60 and fund_flow < 50:
        detail = []
        if margin_growth is not None:
            detail.append(f"两融余额20日变化 {margin_growth:.2%}")
        if main_money is not None:
            detail.append(f"主力净流入占比 {main_money:.2%}")
        suffix = f"；{'，'.join(detail)}" if detail else ""
        lines.append(
            "- 价格修复的资金确认不足: "
            f"技术面 {_temperature_text(technical)}，"
            f"资金面 {_temperature_text(fund_flow)}{suffix}。"
        )
    if (
        investor_temperature is not None
        and investor_temperature >= 80
        and (sentiment is None or sentiment < 65)
    ):
        lines.append(
            "- 开户热度与日频情绪背离: "
            f"新增投资者温度 {_temperature_text(investor_temperature)}，"
            f"情绪面 {_temperature_text(sentiment)}；慢变量高温尚未等同于当日全面过热。"
        )
    sentiment_item = _dimension_item(dimensions, "sentiment")
    subgroup_values = sentiment_item.get("subgroups", {}) if sentiment_item else {}
    activity_temperature = _as_float(subgroup_values.get("activity"))
    if (
        sentiment is not None
        and activity_temperature is not None
        and activity_temperature - sentiment >= 25
    ):
        lines.append(
            "- 活跃水位与动能背离: "
            f"活跃水位 {_temperature_text(activity_temperature)}，"
            f"动能 {_temperature_text(sentiment)}；高换手低位动能，呈现派发/退潮特征。"
        )
    if valuation is not None and macro is not None and valuation >= 80 and macro >= 60:
        lines.append(
            "- 估值约束与流动性支撑并存: "
            f"估值面 {_temperature_text(valuation)}，宏观流动性 {_temperature_text(macro)}；"
            "低利率能支撑风险偏好，但高估值会压缩追高安全边际。"
        )
    if (
        fundamental is not None
        and fundamental >= 50
        and _has_dataset_status(facts, "sw_2021_fs_", {"lagging"})
    ):
        lines.append(
            "- 基本面分数可用但正式财报偏慢: "
            f"基本面 {_temperature_text(fundamental)}；季频行业财报只作底座，"
            "近20日变化应优先看预告和研报上修事实。"
        )

    game_state = _metric_text(facts, "capital_game_state_observation")
    cap_div_score = _metric_float(facts, "capital_divergence_score_observation")
    winner_rate = _metric_float(facts, "capital_winner_rate_observation")
    etf_pct = _metric_float(facts, "capital_etf_percentile_observation")
    margin_pct = _metric_float(facts, "capital_margin_percentile_observation")

    if game_state == "BOTTOM_SUPPORT":
        etf_pct_str = f" (ETF流入历史 {etf_pct:.1f}% 分位)" if etf_pct is not None else ""
        lines.append(
            f"- 资金博弈 [国家队护盘托底]: 宽基 ETF 逆周期强力托底承接{etf_pct_str}，"
            "两融杠杆趋于出清，呈现典型政策底/流动性冰点特征。"
        )
    elif game_state == "HIGH_DISTRIBUTION":
        margin_pct_str = f" (两融买入历史 {margin_pct:.1f}% 分位)" if margin_pct is not None else ""
        lines.append(
            f"- 资金博弈 [主力高位派发]: 大资金借 ETF 等工具天量减持兑现，两融与散户高位接盘{margin_pct_str}，"
            "提示微观筹码高位换手派发与天量滞涨风险。"
        )
    elif game_state == "LEVERAGE_EUPHORIA":
        lines.append(
            "- 资金博弈 [杠杆情绪狂热]: 两融杠杆资金处于历史极高位 (95%+ 分位)，"
            "追涨情绪过热，需高度警惕一致性获利兑现引发的踩踏。"
        )
    elif game_state == "ICE_PANIC":
        lines.append(
            "- 资金博弈 [冰点无序踩踏]: 主力订单流与两融杠杆双双处于历史低谷 (10% 分位以内)，"
            "做多意愿极度匮乏，处于情绪冰点期。"
        )
    elif game_state == "ALL_RESONANCE":
        lines.append(
            "- 资金博弈 [多头共振主升]: 国家队/被动资金、两融杠杆与大单主力多路全线同向净流入，"
            "多头流动性共振充沛，主升动能强劲。"
        )
    elif cap_div_score is not None:
        if cap_div_score >= 35.0:
            lines.append(
                f"- 资金博弈分歧: 主力机构承接显著高于散户杠杆盘 (分歧得分 {cap_div_score:+.1f})，低位承接特征明显。"
            )
        elif cap_div_score <= -35.0:
            lines.append(
                f"- 资金博弈分歧: 散户与两融接盘显著高于主力资金 (分歧得分 {cap_div_score:+.1f})，警惕高位筹码换手。"
            )

    if winner_rate is not None:
        if winner_rate >= 85.0:
            lines.append(
                f"- 筹码获利盘压力: 全市场平均获利盘胜率达 {winner_rate:.1f}%，处于极高位，"
                "警惕获利盘一致性兑现导致的波动踩踏。"
            )
        elif winner_rate <= 15.0:
            lines.append(
                f"- 筹码深度超跌出清: 全市场平均获利盘仅 {winner_rate:.1f}% (深度套牢区)，"
                "边际割肉抛压显著衰竭，空头动能处于低位。"
            )
    return lines or ["- 暂未发现需要单独强调的维度背离。"]


def _dimension_temperature(dimensions: list[dict[str, Any]], dimension_id: str) -> float | None:
    for item in dimensions:
        if str(item.get("dimension_id")) == dimension_id:
            return _as_float(item.get("temperature"))
    return None


def _dimension_item(dimensions: list[dict[str, Any]], dimension_id: str) -> dict[str, Any] | None:
    for item in dimensions:
        if str(item.get("dimension_id")) == dimension_id:
            return item
    return None


def _metric_row_by_id(facts: pl.DataFrame, metric_id: str) -> dict[str, Any] | None:
    if facts.is_empty() or "metric_id" not in facts.columns:
        return None
    filtered = facts.filter(facts["metric_id"] == metric_id)
    if filtered.is_empty():
        return None
    return filtered.to_dicts()[0]


def _metric_float(facts: pl.DataFrame, metric_id: str) -> float | None:
    row = _metric_row_by_id(facts, metric_id)
    if not row:
        return None
    return _as_float(row.get("value_float"))


def _metric_text(facts: pl.DataFrame, metric_id: str) -> str | None:
    row = _metric_row_by_id(facts, metric_id)
    if not row:
        return None
    val = row.get("value_text")
    return str(val).strip() if val else None


def _has_dataset_status(facts: pl.DataFrame, dataset_prefix: str, statuses: set[str]) -> bool:
    if facts.is_empty() or "category" not in facts.columns or "status" not in facts.columns:
        return False
    filtered = facts.filter(facts["category"] == "data_watermark")
    if filtered.is_empty():
        return False
    for row in filtered.to_dicts():
        dataset = str(row.get("dataset") or "")
        status = str(row.get("status") or "")
        if (not dataset_prefix or dataset.startswith(dataset_prefix)) and status in statuses:
            return True
    return False


def _text_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _join_text_items(items: list[str]) -> str:
    return "；".join(item.rstrip("。；; ") for item in items if item.strip())


__all__ = [
    "evaluate_fast_slow_section",
    "evaluate_key_divergences",
    "evaluate_systemic_risk_section",
]
