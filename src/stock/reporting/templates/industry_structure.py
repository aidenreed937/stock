"""行业结构分析报告模板。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from stock.analytics.pipelines.industry_structure.interpretation import (
    evaluate_key_takeaways as _key_takeaway_section,
)
from stock.analytics.pipelines.industry_structure.interpretation import (
    evaluate_one_line_summary as _one_line_summary,
)
from stock.analytics.pipelines.industry_structure.interpretation import (
    evaluate_short_term_rhythm as _short_term_rhythm_section,
)
from stock.analytics.pipelines.industry_structure.interpretation import (
    evaluate_structure_radar as _structure_radar_section,
)
from stock.analytics.pipelines.industry_structure.interpretation import (
    evaluate_theme_types as _theme_type_section,
)
from stock.analytics.pipelines.industry_structure.interpretation import (
    get_fundamental_status_interpretation as _fundamental_status_interpretation,
)
from stock.analytics.pipelines.industry_structure.interpretation import (
    get_fundamental_status_label as _fundamental_status_label,
)
from stock.analytics.pipelines.industry_structure.interpretation import (
    get_structure_health_level as _structure_health_level,
)
from stock.reporting.core.watermark import human_watermark_issue_lines
from stock.reporting.engine.renderer import ReportRenderer

if TYPE_CHECKING:
    from stock.analytics.pipelines.industry_structure.config import IndustryStructureConfig


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
    facts_sec = "\n".join(_facts_sections(facts)).strip()
    context = {
        "title": config.title,
        "manifest": manifest,
        "medium_windows_str": ", ".join(str(value) for value in manifest.get("medium_windows", [])),
        "scores": scores,
        "weights_text": _weights_text(scores.get("score_weights", {})),
        "trend_diagnostic_lines": _trend_diagnostic_section(scores),
        "structure_health_lines": _structure_health_section(scores),
        "fundamental_status_lines": _fundamental_status_section(scores),
        "methodology_lines": _methodology_sections(scores),
        "panel_table_lines": _panel_table(industry_panel, limit=10),
        "score_group_lines": _score_group_sections(scores),
        "facts_sections": facts_sec,
    }
    return ReportRenderer.get_instance().render("industry/structure.md.j2", context)


def render_human_report_markdown(
    *,
    config: IndustryStructureConfig,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    facts: pl.DataFrame,
    industry_panel: pl.DataFrame,
) -> str:
    """渲染面向人工阅读的 Markdown 报告。"""
    context = {
        "title": config.title,
        "manifest": manifest,
        "scores": scores,
        "structure_health_level": _structure_health_level(scores),
        "one_line_summary": _one_line_summary(scores),
        "human_trend_lines": _human_trend_lines(scores),
        "reading_guide_lines": _human_reading_guide(scores),
        "key_takeaway_lines": _key_takeaway_section(industry_panel, scores),
        "structure_health_lines": _structure_health_section(scores),
        "priority_lines": _human_priority_sections(scores),
        "structure_radar_lines": _structure_radar_section(industry_panel, scores),
        "theme_type_lines": _theme_type_section(industry_panel),
        "short_term_rhythm_lines": _short_term_rhythm_section(industry_panel),
        "lagging_direction_lines": _lagging_direction_section(scores),
        "panel_table_lines": _panel_table(industry_panel, limit=12),
        "interpretation_lines": [
            "- 行业结构分用于方向筛选与强弱排序，不替代六维市场温度计，不直接给仓位建议。",
            (
                "- TCR(20日成交占比)与拥挤温度提示成交集中度与交易拥挤风险，"
                "不宜将高TCR行业直接视为低风险配置方向。"
            ),
            "- 行业资金流由个股 moneyflow 按申万成分聚合，资金确认不进入结构总分。",
            "- 标签不是互斥分组，同一行业可以同时是强势主线和拥挤风险。",
            "- 动量与拥挤度为日频，估值受价格驱动，财报为季频底座；指标缺失时以可用子项重归一。",
        ],
        "limit_sections": "\n".join(_data_limit_sections(facts)).strip(),
    }
    return ReportRenderer.get_instance().render("industry/structure_human.md.j2", context)


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
        (
            "| 排名 | 行业 | 结构分 | 20日收益 | 60日收益 | TCR(20日成交占比) | "
            "20日资金净流入占比 | 标签 |"
        ),
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    if panel.is_empty():
        return [*lines, "| - | - | - | - | - | - | - | 无可用行业面板 |"]
    rows = panel.sort("structure_score", descending=True, nulls_last=True).head(limit)
    for row in rows.to_dicts():
        lines.append(
            (
                "| {rank} | {name} | {score} | {ret20} | {ret60} | {tcr} | {money_flow} | {tags} |"
            ).format(
                rank=row.get("structure_rank") or "",
                name=row.get("industry_name") or row.get("industry_code"),
                score=_value_text(row.get("structure_score")),
                ret20=_value_text(row.get("return_20d")),
                ret60=_value_text(row.get("return_60d")),
                tcr=_value_text(row.get("tcr")),
                money_flow=_value_text(row.get("money_net_inflow_share_20d")),
                tags=row.get("tags") or "",
            )
        )
    if panel.height > limit:
        lines.append("")
        lines.append(
            f"> 注：总览表默认展示前 {limit} 个行业，完整 31 行业数据见 "
            "industry_panel.parquet / scores.json。"
        )
    return lines


def _score_group_sections(scores: dict[str, Any]) -> list[str]:
    sections = [
        ("强势主线", scores.get("strong_trends", [])),
        ("低估改善", scores.get("undervalued_improving", [])),
        ("拥挤风险", scores.get("crowded_risk", [])),
        ("资金确认", scores.get("fund_flow_confirmed", [])),
        ("资金流出压力", scores.get("fund_flow_pressure", [])),
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
                (
                    "- {name}: 分数 {score}, 20日收益 {ret20}, TCR {tcr}, "
                    "20日资金净流入占比 {money_flow}, 标签 {tags}"
                ).format(
                    name=row.get("industry_name") or row.get("industry_code"),
                    score=_value_text(row.get("score")),
                    ret20=_value_text(row.get("return_20d")),
                    tcr=_value_text(row.get("tcr")),
                    money_flow=_value_text(row.get("money_net_inflow_share_20d")),
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
    for key in (
        "momentum_score",
        "valuation_score",
        "fundamental_score",
        "crowding_score",
        "fund_flow_score",
    ):
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
    lines.append(f"- 资金确认: {_names(scores.get('fund_flow_confirmed', []))}")
    lines.append(f"- 资金流出压力: {_names(scores.get('fund_flow_pressure', []))}")
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


def _human_reading_guide(scores: dict[str, Any]) -> list[str]:
    return [
        "- 1. 先看结构健康度：判断20日短线修复与60日中期确认是否同向；结构分高不等于20日涨幅最高。",
        "- 2. 筛方向避拥挤：优先观察结构分领先与低估改善方向，回避高拥挤与景气承压标签。",
        "- 3. 跟踪短线节奏：结合5日/20日收益差跟踪轮动主线与资金流入流出变化。",
    ]


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
        lines.extend(human_watermark_issue_lines(issues, max_groups=8))
        if any(row.get("dataset") == "index_classify" for row in issues):
            lines.append(
                "- 行业分类字典缺失时，行业范围回退为申万行业行情可用代码；"
                "名称再由申万行业行情或理杏仁估值表回填。"
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


def _panel_rows(panel: pl.DataFrame) -> list[dict[str, Any]]:
    return [] if panel.is_empty() else panel.to_dicts()


def _top_rows(
    rows: list[dict[str, Any]], key: str, *, limit: int, descending: bool = True
) -> list[dict[str, Any]]:
    valid = [row for row in rows if _as_float(row.get(key)) is not None]
    return sorted(
        valid,
        key=lambda row: _as_float(row.get(key)) or 0.0,
        reverse=descending,
    )[:limit]


def _industry_name(row: dict[str, Any]) -> str:
    return str(row.get("industry_name") or row.get("industry_code") or "")


def _industry_list(
    rows: list[dict[str, Any]],
    metrics: tuple[tuple[str, str, str], ...],
    *,
    limit: int = 6,
) -> str:
    if not rows:
        return "无"
    parts = []
    for row in rows[:limit]:
        metric_parts = []
        for label, key, suffix in metrics:
            value = _metric_value_text(row, key, suffix)
            if value:
                metric_parts.append(f"{label}{value}{suffix}")
        metrics_text = f"({', '.join(metric_parts)})" if metric_parts else ""
        parts.append(f"{_industry_name(row)}{metrics_text}")
    return "、".join(parts)


def _metric_value_text(row: dict[str, Any], key: str, suffix: str) -> str:
    value = _as_float(row.get(key))
    if value is None:
        return _value_text(row.get(key))
    if key == "dividend_yield" and suffix == "%" and abs(value) <= 1:
        value *= 100
    return f"{value:.2f}"


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
