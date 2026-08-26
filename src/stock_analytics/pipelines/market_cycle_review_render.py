"""市场跨周期复盘的 Markdown 渲染逻辑。"""

from __future__ import annotations

import math
from typing import Any

from stock_analytics.pipelines.market_cycle_review_analysis import (
    _format_counts,
    _to_float,
)


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# A 股市场跨周期复盘",
        "",
        f"- 起止日期: {payload['start_date']} 至 {payload['end_date']}",
        f"- 交易日数: {payload['date_count']}",
        f"- 一致性校验: {payload.get('consistency', {}).get('status', 'not_checked')}",
        "- 口径: 只读取已落盘市场温度、行业结构、投资者简报和量化投研简报产物；"
        "不使用新闻、政策或模型记忆。",
        "",
        "## 市场摘要",
        "",
    ]
    lines.extend(_market_summary_lines(payload["market_summary"]))
    lines.extend(["", "## 阶段变化", ""])
    lines.extend(_phase_table(payload["phase_summary"]))
    lines.extend(["", "## 重要信号日", ""])
    lines.extend(_signal_table(payload["signal_days"]))
    lines.extend(["", "## 行业资金与结构频率", ""])
    lines.extend(_industry_frequency_lines(payload["industry_frequency"]))
    lines.extend(["", "## 量化投研性质与排雷", ""])
    lines.extend(_quant_brief_lines(payload.get("quant_brief", {})))
    lines.extend(["", "## 阶段研判总结", ""])
    lines.extend(_stage_conclusion_lines(payload))
    lines.extend(["", "## 使用提醒", ""])
    lines.extend(
        [
            "- 综合温度用于判断系统风险和参与环境，行业结构用于判断方向，不要混为一个分数。",
            "- 20日扩散强但60日确认弱时，优先按短线修复处理。",
            "- 资金温度、两融变化和主力净流入用于确认行情质量；价格先行不等于资金确认。",
            "- 高TCR或高拥挤温度行业可以继续交易活跃，但不应直接视为低风险配置方向。",
            "- quant_brief 缺失的历史日期按兼容模式保留；有 quant 产物时只读取同日性质、排雷和行业方向。",
        ]
    )
    return "\n".join(lines) + "\n"


def _stage_conclusion_lines(payload: dict[str, Any]) -> list[str]:
    summary = payload["market_summary"]
    series = summary["series"]
    comp_start = series["composite"]["start"]
    comp_end = series["composite"]["end"]
    ff_end = series["fund_flow"]["end"]
    tech_end = series["technical"]["end"]
    pos20_end = round(series["positive_return_20d_count"]["end"])
    pos60_end = round(series["positive_return_60d_count"]["end"])

    return [
        (
            f"- 区间核心特征: 综合温度由 {comp_start:.2f} 运行至 {comp_end:.2f}，"
            f"短线技术面({tech_end:.2f})与20日行业扩散({pos20_end}/31)显著修复，"
            f"但资金面({ff_end:.2f})未形成同步强化，"
            f"且60日中期确认({pos60_end}/31)仍然偏弱。"
        ),
        (
            "- 操作启示: 当前市场结构呈现“短线修复快于中期确认”特征，"
            "配置上适宜沿低估且不拥挤的方向逢低观察，避免在资金未确认的高温拥挤板块盲目追高。"
        ),
        (
            "- 下阶段核心观测: 重点跟踪资金面温度能否站稳50以上、两融与主力资金是否企稳，"
            "以及站上60日线行业数能否稳步扩展。"
        ),
    ]


def _format_series_val(key: str, val: float) -> str:
    if key in {"positive_return_20d_count", "positive_return_60d_count"}:
        return str(round(val))
    return f"{val:.2f}"


def _market_summary_lines(summary: dict[str, Any]) -> list[str]:
    series = summary["series"]
    comp_start = _format_series_val("composite", series["composite"]["start"])
    comp_end = _format_series_val("composite", series["composite"]["end"])
    comp_mean = _format_series_val("composite", series["composite"]["mean"])
    comp_min_date = series["composite"]["min"]["date"]
    comp_min_val = _format_series_val("composite", series["composite"]["min"]["value"])
    comp_max_date = series["composite"]["max"]["date"]
    comp_max_val = _format_series_val("composite", series["composite"]["max"]["value"])

    fund_start = _format_series_val("fund_flow", series["fund_flow"]["start"])
    fund_end = _format_series_val("fund_flow", series["fund_flow"]["end"])
    fund_mean = _format_series_val("fund_flow", series["fund_flow"]["mean"])

    tech_start = _format_series_val("technical", series["technical"]["start"])
    tech_end = _format_series_val("technical", series["technical"]["end"])
    tech_mean = _format_series_val("technical", series["technical"]["mean"])

    ret20_start = _format_series_val(
        "positive_return_20d_count", series["positive_return_20d_count"]["start"]
    )
    ret20_end = _format_series_val(
        "positive_return_20d_count", series["positive_return_20d_count"]["end"]
    )
    ret60_start = _format_series_val(
        "positive_return_60d_count", series["positive_return_60d_count"]["start"]
    )
    ret60_end = _format_series_val(
        "positive_return_60d_count", series["positive_return_60d_count"]["end"]
    )

    fast_lines = []
    for key, label in (
        ("fast_temperature", "快温度"),
        ("slow_temperature", "慢温度"),
        ("divergence", "背离(快-慢)"),
    ):
        item = series.get(key)
        if not isinstance(item, dict) or item.get("status") == "missing":
            continue
        fast_lines.append(
            f"- {label}: {_format_series_val(key, item['start'])} -> "
            f"{_format_series_val(key, item['end'])}，均值 {_format_series_val(key, item['mean'])}，"
            f"区间最低 {item['min']['date']}={_format_series_val(key, item['min']['value'])}，"
            f"最高 {item['max']['date']}={_format_series_val(key, item['max']['value'])}。"
        )

    lines = [
        (
            f"- 综合温度: {comp_start} -> {comp_end}，均值 {comp_mean}，"
            f"区间最低 {comp_min_date}={comp_min_val}，"
            f"最高 {comp_max_date}={comp_max_val}。"
        ),
        f"- 资金面: {fund_start} -> {fund_end}，均值 {fund_mean}。",
        f"- 技术面: {tech_start} -> {tech_end}，均值 {tech_mean}。",
        (
            f"- 20日上涨行业数: {ret20_start} -> {ret20_end}；"
            f"60日上涨行业数: {ret60_start} -> {ret60_end}。"
        ),
        f"- 系统风险分布: {_format_counts(summary['risk_level_counts'])}。",
        f"- 结构健康度分布: {_format_counts(summary['structure_health_counts'])}。",
        *fast_lines,
    ]
    if summary.get("divergence_level_counts"):
        labels = {"synchronized": "快慢同步", "divergent": "分歧观察", "extreme": "深度背离"}
        level_text = "，".join(
            f"{labels.get(key, key)} {count}天"
            for key, count in summary["divergence_level_counts"].items()
        )
        lines.append(f"- 快慢背离分布: {level_text}。")
    return lines


def _phase_table(phases: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 阶段 | 综合 | 系统风险 | 资金 | 技术 | 情绪 | 20日上涨行业 | 60日上涨行业 |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in phases:
        lines.append(
            f"| {row['start_date']}..{row['end_date']} | {_fmt(row['composite'])} | "
            f"{row.get('risk_level', '--')} | "
            f"{_fmt(row['fund_flow'])} | {_fmt(row['technical'])} | "
            f"{_fmt(row['sentiment'])} | {_fmt(row['positive_return_20d_count'])} | "
            f"{_fmt(row['positive_return_60d_count'])} |"
        )
    return lines


def _reason_priority(reason: str) -> int:
    if "系统风险切换为" in reason or "结构健康度切换为" in reason or "区间起点" in reason:
        return 1
    if "综合温度" in reason or "单日最大" in reason:
        return 2
    if "最高" in reason or "最低" in reason:
        return 3
    if "上穿" in reason or "下穿" in reason:
        return 4
    return 5


def _signal_table(signal_days: list[dict[str, Any]], limit: int = 24) -> list[str]:
    lines = [
        "| 日期 | 综合 | 风险 | 资金 | 技术 | 20日/60日行业 | 信号 |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    selected = _important_signal_days(signal_days, limit)
    for row in selected:
        sorted_reasons = sorted(row["reasons"], key=_reason_priority)
        reasons = "；".join(sorted_reasons[:2])
        divergence = row.get("divergence")
        divergence_text = (
            f"，背离{divergence:+.1f}"
            if divergence is not None and math.isfinite(float(divergence))
            else ""
        )
        lines.append(
            f"| {row['date']} | {_fmt(row['composite'])} | {row['risk_level']} | "
            f"{_fmt(row['fund_flow'])} | {_fmt(row['technical'])} | "
            f"{row['positive_return_20d_count']}/{row['positive_return_60d_count']} | "
            f"{reasons}{divergence_text} |"
        )
    return lines


def _important_signal_days(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    priority_words = ("区间", "最高", "最低", "切换", "上穿 20", "下穿 3", "最大")
    ranked = sorted(
        rows,
        key=lambda row: sum(
            any(word in reason for word in priority_words) for reason in row["reasons"]
        ),
        reverse=True,
    )
    selected_dates = {row["date"] for row in ranked[:limit]}
    return [row for row in rows if row["date"] in selected_dates]


def _industry_frequency_lines(freq: dict[str, Any]) -> list[str]:
    return [
        f"- 候选行业出现频率 Top: {_format_industries(freq['brief_candidate_counts'], 8)}。",
        f"- 拥挤风险出现频率 Top: {_format_industries(freq['brief_risk_counts'], 8)}。",
        f"- 落后方向出现频率 Top: {_format_industries(freq['brief_lagging_counts'], 8)}。",
        f"- 量化优先方向出现频率 Top: {_format_industries(freq['quant_priority_counts'], 8)}。",
        f"- 量化回避方向出现频率 Top: {_format_industries(freq['quant_avoid_counts'], 8)}。",
        f"- 结构分 Top5 频率 Top: {_format_industries(freq['top5_counts'], 8)}。",
        f"- 拥挤温度>=80 频率 Top: {_format_industries(freq['crowding_counts'], 8)}。",
        f"- TCR 边际上升 Top: {_format_tcr_changes(freq['tcr_change'][:8])}。",
        f"- TCR 边际下降 Top: {_format_tcr_changes(list(reversed(freq['tcr_change'][-8:])))}。",
    ]


def _quant_brief_lines(quant: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    missing_dates = quant.get("missing_dates", [])
    if missing_dates:
        lines.append(
            "- quant_brief 缺失日期（legacy compatibility warning）: "
            f"{'、'.join(str(value) for value in missing_dates)}。"
        )
    if not quant.get("available_date_count"):
        lines.append("- 未找到 quant_brief 日期产物，历史区间未纳入量化性质和排雷统计。")
        return lines
    nature = _format_counts(quant.get("nature_counts", {})) or "无"
    veto = _format_counts(quant.get("veto_status_counts", {})) or "无"
    lines.extend(
        [
            f"- 行情性质分布: {nature}。",
            f"- 一票否决/排雷状态分布: {veto}。",
            f"- 量化优先方向频率 Top: {_format_industries(quant.get('priority_counts', []), 8)}。",
            f"- 量化回避方向频率 Top: {_format_industries(quant.get('avoid_counts', []), 8)}。",
        ]
    )
    return lines


def _format_industries(rows: list[dict[str, Any]], limit: int) -> str:
    return "、".join(f"{row['industry_name']}({row['days']})" for row in rows[:limit]) or "无"


def _format_tcr_changes(rows: list[dict[str, Any]]) -> str:
    return "、".join(f"{row['industry_name']}({row['delta']:+.2f})" for row in rows) or "无"


def _fmt(value: Any) -> str:
    number = _to_float(value)
    return f"{number:.2f}" if math.isfinite(number) else ""
