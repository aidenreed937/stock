"""行业结构分析报告模板。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from stock.analytics.industry_structure.config import IndustryStructureConfig


def build_report_json(
    *,
    config: IndustryStructureConfig,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    facts: pl.DataFrame,
    industry_panel: pl.DataFrame,
) -> dict[str, Any]:
    """构造机器可读报告。"""
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "manifest": manifest,
        "scores": scores,
        "fact_summary": summarize_facts(facts),
        "industry_panel_preview": _panel_preview(industry_panel),
    }


def render_report_markdown(
    *,
    config: IndustryStructureConfig,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    facts: pl.DataFrame,
    industry_panel: pl.DataFrame,
) -> str:
    """渲染 Markdown 报告。"""
    lines = [
        f"# {config.title}",
        "",
        f"- 基准日期: {manifest['as_of_date']}",
        f"- 主窗口: 最近 {manifest['main_window']} 个已落盘申万行业交易日",
        f"- 中期窗口: {', '.join(str(value) for value in manifest['medium_windows'])} 日",
        f"- 产物运行 ID: {manifest['run_id']}",
        "",
        "## 行业结构摘要",
        "",
        f"- 行业数: {scores['industry_count']}",
        f"- 可评分行业数: {scores['scored_industry_count']}",
        f"- 权重: {_weights_text(scores['score_weights'])}",
        "",
        "## 趋势诊断",
        "",
        *_trend_diagnostic_section(scores),
        "",
        "## 结构健康度",
        "",
        *_structure_health_section(scores),
        "",
        "## 基本面状态",
        "",
        *_fundamental_status_section(scores),
        "",
        "## 评分口径",
        "",
        *_methodology_sections(scores),
        "",
        "## 结构分 Top 10",
        "",
        *_panel_table(industry_panel, limit=10),
        "",
        "## 信号分组",
        "",
        *_score_group_sections(scores),
    ]
    lines.extend(_facts_sections(facts))
    return "\n".join(lines) + "\n"


def render_human_report_markdown(
    *,
    config: IndustryStructureConfig,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    facts: pl.DataFrame,
    industry_panel: pl.DataFrame,
) -> str:
    """渲染面向人工阅读的 Markdown 报告。"""
    lines = [
        f"# {config.title}人工阅读版",
        "",
        f"- 基准日期: {manifest['as_of_date']}",
        "- 观察窗口: 5/10 日短线、20 日主窗口、60/120 日中期趋势",
        f"- 行业覆盖: {scores['scored_industry_count']} / {scores['industry_count']}",
        "",
        "## 一句话结论",
        "",
        _one_line_summary(scores),
        *_human_trend_lines(scores),
        "",
        "## 结构健康度",
        "",
        *_structure_health_section(scores),
        "",
        "## 优先观察",
        "",
        *_human_priority_sections(scores),
        "",
        "## 落后方向",
        "",
        *_lagging_direction_section(scores),
        "",
        "## 行业总览",
        "",
        *_panel_table(industry_panel, limit=12),
        "",
        "## 解读口径",
        "",
        "- 行业结构分用于排序，不等同于市场综合温度，也不直接给仓位。",
        "- TCR 是最近20个行业交易日的行业成交额占比均值，拥挤温度越高代表成交越集中。",
        "- 标签不是互斥分组，同一行业可以同时是强势主线和拥挤风险。",
        "- 动量和拥挤度是日频，估值是日频但受价格驱动，行业财报是季频慢变量底座。",
        "- 缺失估值、财报或基准指数时，对可用子项重归一，不用外部记忆补值。",
    ]
    lines.extend(_data_limit_sections(facts))
    return "\n".join(lines) + "\n"


def summarize_facts(facts: pl.DataFrame) -> dict[str, Any]:
    """汇总事实表状态。"""
    if facts.is_empty():
        return {"rows": 0, "by_status": {}, "by_category": {}}
    return {
        "rows": facts.height,
        "by_status": _count_by(facts, "status"),
        "by_category": _count_by(facts, "category"),
    }


def _panel_preview(panel: pl.DataFrame, limit: int = 20) -> list[dict[str, Any]]:
    if panel.is_empty():
        return []
    return panel.head(limit).to_dicts()


def _panel_table(panel: pl.DataFrame, limit: int) -> list[str]:
    lines = [
        "| 排名 | 行业 | 结构分 | 20日收益 | 60日收益 | TCR(20日成交占比) | 标签 |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    if panel.is_empty():
        return [*lines, "| - | - | - | - | - | - | 无可用行业面板 |"]
    rows = panel.sort("structure_score", descending=True, nulls_last=True).head(limit)
    for row in rows.to_dicts():
        lines.append(
            "| {rank} | {name} | {score} | {ret20} | {ret60} | {tcr} | {tags} |".format(
                rank=row.get("structure_rank") or "",
                name=row.get("industry_name") or row.get("industry_code"),
                score=_value_text(row.get("structure_score")),
                ret20=_value_text(row.get("return_20d")),
                ret60=_value_text(row.get("return_60d")),
                tcr=_value_text(row.get("tcr")),
                tags=row.get("tags") or "",
            )
        )
    return lines


def _score_group_sections(scores: dict[str, Any]) -> list[str]:
    sections = [
        ("强势主线", scores.get("strong_trends", [])),
        ("低估改善", scores.get("undervalued_improving", [])),
        ("拥挤风险", scores.get("crowded_risk", [])),
        ("落后方向", scores.get("lagging_or_weak", [])),
    ]
    lines: list[str] = []
    for title, rows in sections:
        lines.extend(["", f"### {title}", ""])
        if not rows:
            lines.append("- 无")
            continue
        for row in rows:
            lines.append(
                "- {name}: 分数 {score}, 20日收益 {ret20}, TCR {tcr}, 标签 {tags}".format(
                    name=row.get("industry_name") or row.get("industry_code"),
                    score=_value_text(row.get("score")),
                    ret20=_value_text(row.get("return_20d")),
                    tcr=_value_text(row.get("tcr")),
                    tags=row.get("tags") or "",
                )
            )
    return lines


def _trend_diagnostic_section(scores: dict[str, Any]) -> list[str]:
    diagnostic = scores.get("trend_diagnostics", {})
    if not isinstance(diagnostic, dict):
        return ["- 趋势诊断不可用。"]
    lines = [f"- 结论: {diagnostic.get('message', '趋势诊断不可用。')}"]
    median_20d = _value_text(diagnostic.get("median_return_20d"))
    median_60d = _value_text(diagnostic.get("median_return_60d"))
    lines.append(
        "- 样本: {scored} 个可评分行业；20日收益为正 {pos20} 个，60日收益为正 {pos60} 个。".format(
            scored=diagnostic.get("scored_industry_count", 0),
            pos20=diagnostic.get("positive_return_20d_count", 0),
            pos60=diagnostic.get("positive_return_60d_count", 0),
        )
    )
    if median_20d or median_60d:
        lines.append(f"- 中位收益: 20日 {median_20d}，60日 {median_60d}。")
    if diagnostic.get("top_count"):
        lines.append(
            "- 结构分前{top_count}行业中，60日收益为负 {negative} 个。".format(
                top_count=diagnostic.get("top_count", 0),
                negative=diagnostic.get("top_negative_60d_count", 0),
            )
        )
    return lines


def _structure_health_section(scores: dict[str, Any]) -> list[str]:
    health = scores.get("structure_health", {})
    if not isinstance(health, dict) or not health:
        return ["- 结构健康度暂不可判定。"]
    return [
        f"- 健康度: {health.get('level', '不可判定')}",
        f"- 结论: {health.get('message', '')}",
        (
            "- 扩散: 20日上涨行业 {pos20}/{total} ({share20}%)，"
            "60日上涨行业 {pos60}/{total} ({share60}%)。"
        ).format(
            pos20=health.get("positive_return_20d_count", 0),
            total=health.get("scored_industry_count", 0),
            share20=_value_text(health.get("positive_return_20d_share")),
            pos60=health.get("positive_return_60d_count", 0),
            share60=_value_text(health.get("positive_return_60d_share")),
        ),
        (
            "- 约束: 结构分前{top_limit}行业中60日仍为负 {top_negative} 个；"
            "拥挤行业 {crowded} 个 ({crowded_share}%)；强势主线 {strong} 个。"
        ).format(
            top_limit=health.get("top_limit", 0),
            top_negative=health.get("top_negative_60d_count", 0),
            crowded=health.get("crowded_industry_count", 0),
            crowded_share=_value_text(health.get("crowded_industry_share")),
            strong=health.get("strong_trend_count", 0),
        ),
    ]


def _methodology_sections(scores: dict[str, Any]) -> list[str]:
    methodology = scores.get("methodology", {})
    if not isinstance(methodology, dict):
        return ["- 评分口径未写入 scores。"]
    field_definitions = methodology.get("field_definitions", {})
    tag_rules = methodology.get("tag_rules", {})
    group_rules = methodology.get("group_rules", {})
    subscores = methodology.get("subscores", {})
    lines = [
        f"- 分数定位: {methodology.get('score_type', '')}",
        f"- 缺失处理: {methodology.get('missing_policy', '')}",
        f"- TCR: {_mapping_value(field_definitions, 'tcr')}",
        f"- 拥挤温度: {_mapping_value(field_definitions, 'crowding_temperature')}",
        f"- 行业映射: {methodology.get('data_mapping', '')}",
        f"- 基本面合成: {_fundamental_blend_text(scores)}",
        "",
        "| 子分 | 组件 | 方向 | 标准化 |",
        "|---|---|---|---|",
    ]
    for key in ("momentum_score", "valuation_score", "fundamental_score", "crowding_score"):
        item = subscores.get(key, {}) if isinstance(subscores, dict) else {}
        components = "；".join(item.get("components", [])) if isinstance(item, dict) else ""
        direction = item.get("direction", "") if isinstance(item, dict) else ""
        normalization = item.get("normalization", "") if isinstance(item, dict) else ""
        lines.append(f"| {key} | {components} | {direction} | {normalization} |")
    lines.extend(["", "标签规则："])
    tag_items = tag_rules.items() if isinstance(tag_rules, dict) else ()
    for label, rule in tag_items:
        lines.append(f"- {label}: {rule}")
    lines.extend(["", "分组规则："])
    group_items = group_rules.items() if isinstance(group_rules, dict) else ()
    for label, rule in group_items:
        lines.append(f"- {label}: {rule}")
    return lines


def _fundamental_status_section(scores: dict[str, Any]) -> list[str]:
    counts = scores.get("fundamental_status_counts", {})
    lines = [
        f"- 合成规则: {_fundamental_blend_text(scores)}",
        f"- 状态分布: {_fundamental_status_counts_text(counts)}",
        f"- 快速基本面领先: {_names(scores.get('fast_fundamental_leaders', []))}",
    ]
    interpretation = _fundamental_status_interpretation(counts)
    if interpretation:
        lines.append(f"- 解读: {interpretation}")
    return lines


def _human_priority_sections(scores: dict[str, Any]) -> list[str]:
    top_structure = scores.get("top_structure", [])
    crowded = scores.get("crowded_risk", [])
    low_valuation = scores.get("low_valuation", [])
    lagging = scores.get("lagging_or_weak", [])
    lines = []
    lines.append(f"- 结构分领先: {_names(top_structure)}")
    lines.append(f"- 动量主线: {_names(scores.get('top_momentum', []))}")
    lines.append(f"- 低估线索: {_names(low_valuation)}")
    lines.append(f"- 快速基本面领先: {_names(scores.get('fast_fundamental_leaders', []))}")
    lines.append(
        "- 基本面状态: "
        f"{_fundamental_status_counts_text(scores.get('fundamental_status_counts', {}))}"
    )
    interpretation = _fundamental_status_interpretation(scores.get("fundamental_status_counts", {}))
    if interpretation:
        lines.append(f"- 基本面读法: {interpretation}")
    lines.append(f"- 拥挤风险: {_names(crowded)}")
    lines.append(f"- 落后方向: {_names(lagging)}")
    return lines


def _lagging_direction_section(scores: dict[str, Any]) -> list[str]:
    rows = scores.get("lagging_or_weak", [])
    lines = [
        "- 判定: 按结构分升序取后5，表示相对落后或组合质量偏弱，不等同于20日收益一定为负。",
        "",
        "| 行业 | 结构分 | 20日收益 | 60日收益 | TCR(20日成交占比) | 标签 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    if not isinstance(rows, list) or not rows:
        return [*lines, "| - | - | - | - | - | 无落后方向样本 |"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(
            "| {name} | {score} | {ret20} | {ret60} | {tcr} | {tags} |".format(
                name=row.get("industry_name") or row.get("industry_code"),
                score=_value_text(row.get("structure_score") or row.get("score")),
                ret20=_value_text(row.get("return_20d")),
                ret60=_value_text(row.get("return_60d")),
                tcr=_value_text(row.get("tcr")),
                tags=row.get("tags") or "",
            )
        )
    return lines


def _human_trend_lines(scores: dict[str, Any]) -> list[str]:
    diagnostic = scores.get("trend_diagnostics", {})
    if not isinstance(diagnostic, dict) or not diagnostic.get("message"):
        return []
    return ["", f"> {diagnostic['message']}"]


def _one_line_summary(scores: dict[str, Any]) -> str:
    top = scores.get("top_structure", [])
    crowded = scores.get("crowded_risk", [])
    lagging = scores.get("lagging_or_weak", [])
    if not top:
        return "行业结构暂不可判定，需要先补齐 sw_daily 等核心事实。"
    top_names = _names(top[:3])
    crowded_names = _names(crowded[:3])
    lagging_names = _names(lagging[:3])
    return (
        f"当前结构分靠前行业为 {top_names}；"
        f"拥挤度需要重点观察 {crowded_names}；"
        f"落后方向为 {lagging_names}。"
        "行业结论用于方向筛选，需与六维市场温度交叉验证。"
    )


def _facts_sections(facts: pl.DataFrame) -> list[str]:
    if facts.is_empty():
        return ["", "## 事实层", "", "无事实记录。"]
    lines = [
        "",
        "## 数据水位",
        "",
        "| 数据源 | 数据集 | 最新日期 | 状态 | 说明 |",
        "|---|---|---|---|---|",
    ]
    watermarks = facts.filter(pl.col("category") == "data_watermark").sort(
        ["data_source", "dataset"]
    )
    for row in watermarks.to_dicts():
        lines.append(
            "| {source} | {dataset} | {value} | {status} | {note} |".format(
                source=row["data_source"],
                dataset=row["dataset"],
                value=row["value_text"],
                status=row["status"],
                note=row["note"],
            )
        )
    return lines


def _data_limit_sections(facts: pl.DataFrame) -> list[str]:
    lines = ["", "## 数据限制", ""]
    issues = []
    if not facts.is_empty():
        issues = facts.filter(
            (pl.col("category") == "data_watermark") & (pl.col("status") != "ok")
        ).to_dicts()
    if issues:
        for row in issues:
            lines.append(
                "- {source}.{dataset}: {status}，{note}".format(
                    source=row["data_source"],
                    dataset=row["dataset"],
                    status=row["status"],
                    note=row["note"],
                )
            )
        if any(row.get("dataset") == "index_classify" for row in issues):
            lines.append(
                "- index_classify 缺失时，行业范围回退为 sw_daily 可用行业代码；"
                "名称再由 sw_daily 或理杏仁估值表回填。"
            )
    else:
        lines.append("- 本次配置内核心数据水位未发现异常。")
    return lines


def _count_by(facts: pl.DataFrame, column: str) -> dict[str, int]:
    return {
        str(row[column]): int(row["len"])
        for row in facts.group_by(column).len().sort(column).to_dicts()
    }


def _weights_text(weights: dict[str, Any]) -> str:
    parts = []
    for key, value in weights.items():
        numeric = _as_float(value)
        if numeric is not None:
            parts.append(f"{key}={numeric:.0%}")
    return " / ".join(parts)


def _names(rows: list[dict[str, Any]]) -> str:
    names = [str(row.get("industry_name") or row.get("industry_code")) for row in rows]
    return "、".join(names) if names else "无"


def _mapping_value(data: object, key: str) -> str:
    if not isinstance(data, dict):
        return ""
    return str(data.get(key, ""))


def _fundamental_blend_text(scores: dict[str, Any]) -> str:
    blend = scores.get("fundamental_blend", {})
    if not isinstance(blend, dict):
        return ""
    return (
        "正式财报超过 {days} 天视为滞后；未滞后时正式财报/快速确认 "
        "{official}/{fast}，滞后时正式财报/快速确认 {stale_official}/{stale_fast}"
    ).format(
        days=blend.get("stale_after_days", ""),
        official=_percent_text(blend.get("official_weight")),
        fast=_percent_text(blend.get("fast_weight")),
        stale_official=_percent_text(blend.get("stale_official_weight")),
        stale_fast=_percent_text(blend.get("stale_fast_weight")),
    )


def _counts_text(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "无"
    return " / ".join(f"{key}={count}" for key, count in value.items())


def _fundamental_status_counts_text(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "无"
    parts = []
    for key, count in value.items():
        label = _fundamental_status_label(str(key))
        parts.append(f"{label} {count} 个行业")
    return " / ".join(parts)


def _fundamental_status_label(status: str) -> str:
    labels = {
        "fresh_blended": "财报未滞后，且已有预告/快报/研报辅助",
        "stale_blended": "财报已滞后，但已有预告/快报/研报辅助",
        "official_only": "仅使用未滞后的正式财报",
        "official_stale": "仅有已滞后的正式财报，缺少快速确认",
        "provisional_fast_only": "仅有预告/快报/研报快速确认",
        "insufficient": "基本面数据不足",
    }
    return labels.get(status, status)


def _fundamental_status_interpretation(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    stale_blended = int(value.get("stale_blended", 0) or 0)
    official_stale = int(value.get("official_stale", 0) or 0)
    provisional_fast_only = int(value.get("provisional_fast_only", 0) or 0)
    insufficient = int(value.get("insufficient", 0) or 0)
    if stale_blended or official_stale:
        return (
            "正式行业财报更新偏慢，当前基本面分主要是中期底座；"
            "有快速确认的行业会提高预告、快报和研报上修权重，"
            "没有快速确认的行业只能保守使用旧财报。"
        )
    if provisional_fast_only:
        return "部分行业缺少正式财报，只能临时参考预告、快报和研报变化。"
    if insufficient:
        return "部分行业基本面样本不足，相关分数只按可用子项重归一。"
    return "正式财报和快速确认数据匹配正常。"


def _percent_text(value: object) -> str:
    numeric = _as_float(value)
    return "" if numeric is None else f"{numeric:.0%}"


def _value_text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, int | float | str):
        return str(value)
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
