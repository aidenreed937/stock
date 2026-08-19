"""市场温度计复杂业务研判与报告段落生成。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stock_reporting.interpretation.market_temperature.bands import (
    _DIMENSION_TIMELINESS,
    _METRIC_LABELS,
    _as_float,
    _temperature_text,
    get_pressure_band,
    get_pressure_comment,
    get_systemic_risk_level,
    get_temperature_band,
)

if TYPE_CHECKING:
    import polars as pl


def evaluate_one_line_summary(dimensions: list[dict[str, Any]], temperature: object) -> str:
    """生成一句话核心结论。"""
    band = get_temperature_band(temperature)
    valid = [item for item in dimensions if _as_float(item.get("temperature")) is not None]
    if not valid:
        return f"综合温度暂不可判定，当前状态为{band}，需要先补齐核心指标事实。"
    hottest = max(valid, key=_score_temperature)
    coldest = min(valid, key=_score_temperature)
    return (
        f"综合温度处于{band}；最高维度是{hottest['name']}({_temperature_text(hottest['temperature'])})，"
        f"最低维度是{coldest['name']}({_temperature_text(coldest['temperature'])})。"
        "解读时优先看高温维度是否由资金和基本面共同确认。"
    )


def evaluate_reading_brief(
    dimensions: list[dict[str, Any]], scores: dict[str, Any], facts: pl.DataFrame
) -> list[str]:
    """生成阅读指引摘要。"""
    composite = scores.get("composite", {})
    composite_temperature = composite.get("temperature") if isinstance(composite, dict) else None
    valid = [item for item in dimensions if _as_float(item.get("temperature")) is not None]
    hot = [item for item in valid if (_as_float(item.get("temperature")) or 0.0) >= 70]
    cold = [item for item in valid if (_as_float(item.get("temperature")) or 0.0) < 40]
    lines = [
        "- 先定市场环境: "
        f"综合温度 {_temperature_text(composite_temperature)}，"
        f"系统性风险 {get_systemic_risk_level(scores)}；"
        "它回答的是整体风险偏好和追高安全边际，不直接等同于行业方向。"
    ]
    if hot:
        lines.append(f"- 高温来源: {_dimension_list_text(hot)}；这些维度决定风险上沿。")
    if cold:
        lines.append(
            f"- 拖累来源: {_dimension_list_text(cold)}；这些维度说明行情质量尚未全面确认。"
        )

    valuation = _dimension_temperature(dimensions, "valuation")
    fund_flow = _dimension_temperature(dimensions, "fund_flow")
    sentiment = _dimension_temperature(dimensions, "sentiment")
    technical = _dimension_temperature(dimensions, "technical")
    fundamental = _dimension_temperature(dimensions, "fundamental")
    macro = _dimension_temperature(dimensions, "macro_liquidity")

    if (
        technical is not None
        and technical < 40
        and any(value is not None and value >= 70 for value in (valuation, fund_flow, sentiment))
    ):
        lines.append(
            "- 最容易误读: 技术面低温不是低风险，而是趋势广度弱；"
            "它衡量最近20个交易日的中位收益和均线宽度，不等同于基准日当天涨跌；"
            "如果估值、资金或情绪同时偏热，通常表示热度集中在少数方向。"
        )
    investor_temperature = _metric_float(facts, "investor_account_temperature")
    if investor_temperature is not None and investor_temperature >= 80:
        if sentiment is not None and sentiment < 65:
            lines.append(
                "- 慢变量情绪: 月度新增投资者处于高温，但日频情绪未同步过热；"
                "这代表参与热度水位高，不代表基准日全面亢奋。"
            )
        else:
            lines.append(
                "- 慢变量情绪: 月度新增投资者处于高温，"
                "需和换手、上涨家数、涨跌停事件一起判断情绪拥挤。"
            )
    if valuation is not None and valuation >= 80:
        lines.append(
            "- 估值约束: 估值高温主要由价格和估值分位驱动，"
            "含义是安全边际收缩，不代表盈利已经同步改善。"
        )
    if fund_flow is not None and fund_flow >= 70 and technical is not None and technical < 40:
        lines.append(
            "- 资金读法: 资金面高温但技术面偏冷时，重点看资金是否集中在少数方向，"
            "需要用行业结构报告验证扩散程度。"
        )
    if fundamental is not None and macro is not None:
        lines.append(
            "- 慢变量读法: 基本面和宏观流动性更多是底座；"
            "月频、季频指标只能说明最新状态，不能解释最近20个交易日内的每一次波动。"
        )
    if _has_pending_short_term(scores):
        lines.append("- 短线节奏: 5/10日短线温度尚未形成正式分数，短节奏优先看行业报告。")
    return lines


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
    return lines or ["- 暂未发现需要单独强调的维度背离。"]


def evaluate_follow_ups(
    dimensions: list[dict[str, Any]],
    facts: pl.DataFrame,
    scores: dict[str, Any],
) -> list[str]:
    """生成后续观察与验证要点。"""
    fund_flow = _dimension_temperature(dimensions, "fund_flow")
    if fund_flow is not None and fund_flow >= 50:
        fund_flow_line = (
            "- 资金确认: 观察资金面高温能否延续，尤其是两融余额、主力净流入是否继续改善；"
            "若趋势广度不跟随，高资金分可能只是集中交易。"
        )
    else:
        fund_flow_line = (
            "- 资金确认: 观察资金面温度是否回到50以上，以及两融余额、主力净流入是否由收缩转为改善。"
        )
    lines = [
        fund_flow_line,
        "- 趋势确认: 观察站上60日线占比是否继续提高，避免只有20日修复而中期趋势未确认。",
    ]
    investor_temperature = _metric_float(facts, "investor_account_temperature")
    if investor_temperature is not None and investor_temperature >= 80:
        lines.append(
            "- 情绪传导: 新增开户已处高温时，继续跟踪换手率、上涨家数和涨跌停事件是否同步升温。"
        )
    if _has_dataset_status(facts, "sw_2021_fs_", {"lagging"}) or _has_dataset_status(
        facts, "", {"lagging"}
    ):
        lines.append("- 慢变量更新: 月频宏观和季频财报更新后再复核基本面、宏观流动性分数。")
    if _has_pending_short_term(scores):
        lines.append("- 短线温度: 短线组件样本不足或尚未就绪，短节奏暂不要当成正式温度分。")
    return lines


def evaluate_interpretation_priority_rows(
    dimensions: list[dict[str, Any]],
) -> list[str]:
    """生成六维解读优先级表格。"""
    rows_by_dimension = {str(item["dimension_id"]): item for item in dimensions}
    lines = [
        "| 层级 | 维度 | 温度 | 跟踪速度 | 读法 |",
        "|---|---|---:|---|---|",
    ]
    for dimension_id, (layer, speed, basis, usage) in _DIMENSION_TIMELINESS.items():
        item = rows_by_dimension.get(dimension_id)
        if item is None:
            continue
        lines.append(
            "| {layer} | {name} | {temperature} | {speed} | {basis}；{usage} |".format(
                layer=layer,
                name=item["name"],
                temperature=_temperature_text(item.get("temperature")),
                speed=speed,
                basis=basis,
                usage=usage,
            )
        )
    return lines


def evaluate_external_pressure_section(facts: pl.DataFrame) -> list[str]:
    """生成外部宏观压力项事实与分档解读行。"""
    metric_ids = (
        "macro_external_pressure_temperature",
        "macro_safe_haven_pressure_temperature",
        "macro_inflation_pressure_temperature",
        "macro_demand_pressure_temperature",
    )
    rows = [_metric_row_by_id(facts, metric_id) for metric_id in metric_ids]
    available = [
        row for row in rows if row is not None and _as_float(row.get("value_float")) is not None
    ]
    if not available:
        return ["- 暂无外部压力项事实；该模块只作风险背景，不进入综合温度。"]

    lines = [
        "- 口径: 分数越高代表外盘对 A 股的额外压力越大；该模块默认 weight=0，不进入六维综合温度。",
        "",
        "| 压力项 | 分数 | 分档 | 读法 |",
        "|---|---:|---|---|",
    ]
    for row in available:
        metric_id = str(row["metric_id"])
        value = _as_float(row.get("value_float"))
        name = _METRIC_LABELS.get(metric_id, metric_id)
        band = get_pressure_band(value)
        comment = get_pressure_comment(metric_id, value)
        lines.append(f"| {name} | {_temperature_text(value)} | {band} | {comment} |")
    return lines


def _score_temperature(item: dict[str, Any]) -> float:
    return _as_float(item.get("temperature")) or 0.0


def _dimension_list_text(rows: list[dict[str, Any]]) -> str:
    parts = [
        f"{item.get('name', '')} {_temperature_text(item.get('temperature'))}"
        for item in rows
        if item.get("name")
    ]
    return "、".join(parts) if parts else "无"


def _dimension_temperature(dimensions: list[dict[str, Any]], dimension_id: str) -> float | None:
    for item in dimensions:
        if str(item.get("dimension_id")) == dimension_id:
            return _as_float(item.get("temperature"))
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


def _has_pending_short_term(scores: dict[str, Any]) -> bool:
    short_term = scores.get("short_term", [])
    if not isinstance(short_term, list):
        return False
    return any(
        isinstance(item, dict) and item.get("status") in {"pending", "insufficient"}
        for item in short_term
    )


def _text_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _join_text_items(items: list[str]) -> str:
    return "；".join(item.rstrip("。；; ") for item in items if item.strip())
