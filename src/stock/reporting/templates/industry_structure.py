"""行业结构分析报告模板。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

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
            "- 行业结构分用于排序，不等同于市场综合温度，也不直接给仓位。",
            "- TCR 是最近20个行业交易日的行业成交额占比均值，拥挤温度越高代表成交越集中。",
            (
                "- 行业资金流由个股 moneyflow 按申万成分聚合，并用个股成交额作分母；"
                "资金确认不进入结构总分。"
            ),
            (
                "- 景气承压/估值极端标签来自行业聚合指标与基本面分位数；"
                "若基本面指标缺失，对应分数回退为中性。"
            ),
            (
                "- 轮动扩散/分化/衰退来自行业收益与均线宽度的横截面离散度；"
                "不是对单一指数走势的预测。"
            ),
            "- 标签不是互斥分组，同一行业可以同时是强势主线和拥挤风险。",
            "- 动量和拥挤度是日频，估值是日频但受价格驱动，行业财报是季频慢变量底座。",
            "- 缺失估值、财报或基准指数时，对可用子项重归一，不用外部记忆补值。",
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
    lines = [
        "- 定位: 这份报告只做行业方向筛选，不替代六维市场温度计，也不直接给仓位。",
        "- 结构分: 看动量、估值、基本面和拥挤度的综合质量；结构分高不等于20日涨幅最高。",
        "- 动量主线: 看资金和价格正在交易的主战场；若同时进入拥挤风险，追高风险更高。",
        "- 低估线索: 看估值约束较小的候选方向；仍要等待动量或基本面确认。",
        "- 资金确认: 看个股资金流是否支持行业行情；这是观察项，不参与结构总分。",
        "- 落后方向: 看相对弱势或组合质量靠后的方向，用于风险排查，不等同于永久回避。",
    ]
    health = scores.get("structure_health", {})
    if isinstance(health, dict) and health.get("level"):
        lines.append(f"- 结构健康: {health.get('level')}；先看20日上涨行业扩散，再看60日是否确认。")
    return lines


def _key_takeaway_section(industry_panel: pl.DataFrame, scores: dict[str, Any]) -> list[str]:
    rows = _panel_rows(industry_panel)
    health = scores.get("structure_health", {})
    lines: list[str] = []
    if isinstance(health, dict) and health:
        total = int(health.get("scored_industry_count", 0) or 0)
        pos20 = int(health.get("positive_return_20d_count", 0) or 0)
        pos60 = int(health.get("positive_return_60d_count", 0) or 0)
        lines.append(
            f"- 扩散状态: 20日上涨行业 {pos20}/{total}，60日上涨行业 {pos60}/{total}；"
            f"{_breadth_comment(pos20, pos60, total)}"
        )
        top_negative = health.get("top_negative_60d_count")
        top_limit = health.get("top_limit")
        if top_negative is not None and top_limit:
            lines.append(
                f"- 中期确认: 结构分前{top_limit}行业中60日仍为负 {top_negative} 个；"
                "领先名单需要再看60日收益是否转正。"
            )

    top_structure = scores.get("top_structure", [])
    top_momentum = scores.get("top_momentum", [])
    if isinstance(top_structure, list) and isinstance(top_momentum, list):
        structure_names = {
            _industry_name(row) for row in top_structure[:5] if isinstance(row, dict)
        }
        momentum_names = {_industry_name(row) for row in top_momentum[:5] if isinstance(row, dict)}
        overlap = sorted(name for name in structure_names & momentum_names if name)
        if overlap:
            lines.append(f"- 结构和动量共振: {'、'.join(overlap)}。")
        elif structure_names and momentum_names:
            lines.append(
                "- 结构和动量分离: 结构分领先与动量主线不重合，"
                "说明交易主线和综合质量最优方向不是同一批行业。"
            )

    if rows:
        tcr_top = _top_rows(rows, "tcr", limit=3)
        if tcr_top:
            lines.append(
                "- 成交集中: "
                f"{_industry_list(tcr_top, (('TCR', 'tcr', '%'),), limit=3)}；"
                "TCR高表示成交占比高，需要观察是否抱团松动。"
            )
        lines.extend(_fund_flow_takeaway_lines(rows))
        weak = _top_rows(
            [
                row
                for row in rows
                if (_as_float(row.get("return_20d")) or 0.0) < 0
                and (_as_float(row.get("return_60d")) or 0.0) < 0
            ],
            "return_20d",
            limit=3,
            descending=False,
        )
        if weak:
            weak_text = _industry_list(
                weak,
                (("20日", "return_20d", "%"), ("60日", "return_60d", "%")),
                limit=3,
            )
            lines.append(f"- 弱势拖累: {weak_text}。")
    return lines or ["- 行业关键判断暂不可用。"]


def _fund_flow_takeaway_lines(rows: list[dict[str, Any]]) -> list[str]:
    fund_flow_metrics = (
        ("资金分", "fund_flow_score", ""),
        ("20日净流入", "money_net_inflow_share_20d", "%"),
    )
    fund_flow_top = _top_rows(
        [row for row in rows if _is_fund_flow_confirmed(row)],
        "fund_flow_score",
        limit=3,
    )
    fund_flow_pressure = _top_rows(
        [row for row in rows if _has_fund_flow_pressure(row)],
        "fund_flow_score",
        limit=3,
        descending=False,
    )
    lines = []
    if fund_flow_top:
        lines.append(f"- 资金确认: {_industry_list(fund_flow_top, fund_flow_metrics)}。")
    if fund_flow_pressure:
        lines.append(f"- 资金流出压力: {_industry_list(fund_flow_pressure, fund_flow_metrics)}。")
    return lines


def _breadth_comment(pos20: int, pos60: int, total: int) -> str:
    if total <= 0:
        return "扩散样本不足。"
    share20 = pos20 / total
    share60 = pos60 / total
    if share20 >= 0.6 and share60 < 0.35:
        return "短线扩散较强，但60日中期确认不足。"
    if share20 < 0.35 and share60 < 0.35:
        return "20日和60日扩散都不足，行业机会更偏局部强势而非全面修复。"
    if share20 >= 0.6 and share60 >= 0.5:
        return "20日和60日扩散同步改善，结构健康度更高。"
    return "扩散信号分化，需要结合主线拥挤度和60日趋势确认。"


def _structure_radar_section(industry_panel: pl.DataFrame, scores: dict[str, Any]) -> list[str]:
    rows = _panel_rows(industry_panel)
    if not rows:
        return ["- 行业面板为空，结构雷达不可用。"]

    positive_60d = _top_rows(
        [row for row in rows if (_as_float(row.get("return_60d")) or 0.0) > 0],
        "return_60d",
        limit=6,
    )
    tcr_top = _top_rows(rows, "tcr", limit=5)
    fund_flow_top = _top_rows(
        [row for row in rows if _is_fund_flow_confirmed(row)],
        "fund_flow_score",
        limit=5,
    )
    top_structure = _top_rows(rows, "structure_score", limit=10)
    unconfirmed = [row for row in top_structure if (_as_float(row.get("return_60d")) or 0.0) < 0]
    weak_fundamental = [row for row in top_structure if _has_weak_fundamental(row)]
    crowded = scores.get("crowded_risk")
    crowded_rows = crowded if isinstance(crowded, list) else []
    tmt_rows = _top_rows(
        [row for row in rows if _industry_name(row) in {"电子", "通信", "计算机", "传媒"}],
        "tcr",
        limit=4,
    )
    return_metrics = (("20日", "return_20d", "%"), ("60日", "return_60d", "%"))
    tcr_metrics = (("TCR", "tcr", "%"),)
    fund_flow_metrics = (
        ("资金分", "fund_flow_score", ""),
        ("20日净流入", "money_net_inflow_share_20d", "%"),
    )
    crowded_metrics = (("20日", "return_20d", "%"), ("TCR", "tcr", "%"))
    fundamental_metrics = (("基本面分", "fundamental_score", ""),)

    lines = [
        f"- 60日正收益行业: {_industry_list(positive_60d, (('60日', 'return_60d', '%'),))}",
        f"- 成交集中 Top: {_industry_list(tcr_top, tcr_metrics)}",
        f"- 资金确认 Top: {_industry_list(fund_flow_top, fund_flow_metrics)}",
        f"- 拥挤风险: {_industry_list(crowded_rows, crowded_metrics)}",
        (f"- 结构领先但60日未确认: {_industry_list(unconfirmed, return_metrics)}"),
        (f"- 结构领先但基本面确认不足: {_industry_list(weak_fundamental, fundamental_metrics)}"),
    ]
    if tmt_rows:
        tmt_tcr = sum(_as_float(row.get("tcr")) or 0.0 for row in tmt_rows)
        lines.append(
            "- 电子/TMT成交集中: "
            f"{_industry_list(tmt_rows, tcr_metrics)}；TMT合计TCR {tmt_tcr:.2f}%。"
        )
    return lines


def _theme_type_section(industry_panel: pl.DataFrame) -> list[str]:
    rows = _panel_rows(industry_panel)
    if not rows:
        return ["- 行业面板为空，主线类型不可用。"]

    low_valuation_improving = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("return_60d")) or 0.0) > 0
            and (_as_float(row.get("valuation_score")) or 0.0) >= 60
            and (_as_float(row.get("fundamental_score")) or 0.0) >= 50
            and (_as_float(row.get("crowding_temperature")) or 0.0) < 70
        ],
        "structure_score",
        limit=3,
    )
    high_beta_strong = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("momentum_score")) or 0.0) >= 70
            and (_as_float(row.get("crowding_temperature")) or 0.0) >= 80
        ],
        "momentum_score",
        limit=3,
    )
    crowded_valuation = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("tcr")) or 0.0) >= 5
            and max(
                _as_float(row.get("pe_percentile_5y")) or 0.0,
                _as_float(row.get("pb_percentile_5y")) or 0.0,
            )
            >= 80
        ],
        "tcr",
        limit=4,
    )
    defensive_crowding = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("pb_percentile_5y")) or 100.0) <= 30
            and _is_high_dividend(row)
            and (_as_float(row.get("crowding_temperature")) or 0.0) >= 80
        ],
        "crowding_temperature",
        limit=3,
    )
    pure_momentum = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("momentum_score")) or 0.0) >= 70 and _has_weak_fundamental(row)
        ],
        "momentum_score",
        limit=3,
    )
    weak_prosperity = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("fundamental_score")) or 100.0) < 30
            or "景气承压" in str(row.get("tags") or "")
        ],
        "crowding_temperature",
        limit=4,
    )
    high_beta_metrics = (
        ("动量分", "momentum_score", ""),
        ("拥挤温度", "crowding_temperature", ""),
    )
    crowded_valuation_metrics = (
        ("TCR", "tcr", "%"),
        ("PE分位", "pe_percentile_5y", ""),
        ("PB分位", "pb_percentile_5y", ""),
    )
    defensive_metrics = (
        ("股息率", "dividend_yield", "%"),
        ("拥挤温度", "crowding_temperature", ""),
    )
    pure_momentum_metrics = (
        ("动量分", "momentum_score", ""),
        ("基本面分", "fundamental_score", ""),
    )
    weak_prosperity_metrics = (
        ("基本面分", "fundamental_score", ""),
        ("拥挤温度", "crowding_temperature", ""),
    )

    return [
        (
            "- 低估改善、不拥挤、中期正收益: "
            f"{_industry_list(low_valuation_improving, (('结构分', 'structure_score', ''),))}"
        ),
        (f"- 高博弈强趋势: {_industry_list(high_beta_strong, high_beta_metrics)}"),
        (
            "- 成交主战场/高估值集中: "
            f"{_industry_list(crowded_valuation, crowded_valuation_metrics)}"
        ),
        (f"- 防御抱团: {_industry_list(defensive_crowding, defensive_metrics)}"),
        (f"- 纯动量/基本面确认不足: {_industry_list(pure_momentum, pure_momentum_metrics)}"),
        (f"- 景气承压: {_industry_list(weak_prosperity, weak_prosperity_metrics)}"),
    ]


def _short_term_rhythm_section(industry_panel: pl.DataFrame) -> list[str]:
    rows = _panel_rows(industry_panel)
    if not rows:
        return ["- 行业面板为空，短线节奏不可用。"]
    accelerating = _top_rows(
        [row for row in rows if (_as_float(row.get("return_5d")) or 0.0) >= 3],
        "return_5d",
        limit=5,
    )
    pullback = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("return_20d")) or 0.0) >= 5
            and (_as_float(row.get("return_5d")) or 0.0) < 0
        ],
        "return_20d",
        limit=5,
    )
    weak = _top_rows(
        [
            row
            for row in rows
            if (_as_float(row.get("return_5d")) or 0.0) < 0
            and (_as_float(row.get("return_20d")) or 0.0) < 0
        ],
        "return_5d",
        limit=5,
        descending=False,
    )
    rhythm_metrics = (("5日", "return_5d", "%"), ("20日", "return_20d", "%"))
    return [
        f"- 5日仍在上行: {_industry_list(accelerating, rhythm_metrics)}",
        f"- 20日强但5日回落: {_industry_list(pullback, rhythm_metrics)}",
        f"- 5日和20日都偏弱: {_industry_list(weak, rhythm_metrics)}",
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


def _structure_health_level(scores: dict[str, Any]) -> str:
    health = scores.get("structure_health", {})
    if not isinstance(health, dict) or not health:
        return "不可判定"
    return str(health.get("level") or "不可判定")


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


def _has_weak_fundamental(row: dict[str, Any]) -> bool:
    score = _as_float(row.get("fundamental_score"))
    return (score is not None and score < 40) or row.get("fundamental_status") in {
        "official_stale",
        "insufficient",
    }


def _is_fund_flow_confirmed(row: dict[str, Any]) -> bool:
    fund_flow = _as_float(row.get("fund_flow_score"))
    money_inflow = _as_float(row.get("money_net_inflow_share_20d"))
    return (
        fund_flow is not None and money_inflow is not None and fund_flow >= 70 and money_inflow > 0
    )


def _has_fund_flow_pressure(row: dict[str, Any]) -> bool:
    fund_flow = _as_float(row.get("fund_flow_score"))
    money_inflow = _as_float(row.get("money_net_inflow_share_20d"))
    return (
        fund_flow is not None and money_inflow is not None and fund_flow <= 30 and money_inflow < 0
    )


def _is_high_dividend(row: dict[str, Any]) -> bool:
    dividend_yield = _as_float(row.get("dividend_yield"))
    if dividend_yield is None:
        return False
    threshold = 0.03 if abs(dividend_yield) <= 1 else 3
    return dividend_yield >= threshold


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
