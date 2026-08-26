"""量化投研简报结构化输出与 Markdown 模板。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stock_reporting.engine.renderer import ReportRenderer
from stock_reporting.interpretation.quant_brief.cross_cycle import (
    cross_cycle_summary,
    evaluate_cross_cycle,
)
from stock_reporting.interpretation.quant_brief.extreme_state import (
    evaluate_extreme_state,
    extreme_state_summary,
)
from stock_reporting.interpretation.quant_brief.formatting import (
    _breadth_text,
    _format_cross_cycle_table,
    _format_extreme_windows,
    _format_funding_health,
    _format_risk_gates,
    _format_rows,
    _format_score_parts,
    _format_trajectory,
    _nested,
    _percent_text,
    _ratio_percent_text,
    _value_text,
)
from stock_reporting.interpretation.quant_brief.interpretation import (
    evaluate_data_quality_notes,
    evaluate_macro,
    evaluate_nature,
    evaluate_reading_notes,
    evaluate_risk_gates,
    evaluate_sector,
    evaluate_veto,
)

if TYPE_CHECKING:
    import polars as pl

    from stock_reporting.interpretation.quant_brief.config import QuantBriefConfig


def build_quant_brief_json(
    *,
    config: QuantBriefConfig,
    manifest: dict[str, Any],
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    industry_panel: pl.DataFrame,
    market_facts: pl.DataFrame | None = None,
    margin_series: pl.DataFrame | None = None,
    history: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """构造量化投研简报机器结构。

    ``margin_series`` 为可选的两融日频序列，用于两融拐点的连续状态判定。
    ``history`` 为可选的市场温度历史索引，用于跨周期矩阵的轨迹修正。
    """
    macro = evaluate_macro(config, market_scores)
    nature = evaluate_nature(config, market_scores, industry_scores, market_facts)
    veto = evaluate_veto(
        config,
        market_scores,
        industry_scores,
        industry_panel,
        market_facts,
        margin_series=margin_series,
    )
    sector = evaluate_sector(config, industry_panel)
    risk_gates = evaluate_risk_gates(
        config,
        market_scores,
        industry_scores,
        industry_panel,
        market_facts,
    )
    position_policy = _build_position_policy(macro, risk_gates)
    cross_cycle = evaluate_cross_cycle(
        config,
        market_scores,
        industry_scores,
        market_facts=market_facts,
        history=history,
    )
    extreme_state = evaluate_extreme_state(config, market_scores, industry_panel)
    data_quality_notes = evaluate_data_quality_notes(
        market_scores,
        industry_scores,
        veto,
        risk_gates,
    )
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "manifest": manifest,
        "macro": macro,
        "nature": nature,
        "veto": veto,
        "sector": sector,
        "risk_gates": risk_gates,
        "position_policy": position_policy,
        "cross_cycle": cross_cycle,
        "extreme_state": extreme_state,
        "data_quality_notes": data_quality_notes,
        "reading_notes": evaluate_reading_notes(macro, nature, veto, sector, risk_gates),
    }


def render_quant_brief_markdown(brief: dict[str, Any]) -> str:
    """渲染量化投研简报 Markdown。"""
    manifest = brief.get("manifest", {})
    macro = brief.get("macro", {})
    nature = brief.get("nature", {})
    veto = brief.get("veto", {})
    sector = brief.get("sector", {})
    risk_gates = brief.get("risk_gates", {})
    position_policy = brief.get("position_policy")
    if not isinstance(position_policy, dict):
        position_policy = _build_position_policy(macro, risk_gates)
    cross_cycle = brief.get("cross_cycle")
    if not isinstance(cross_cycle, dict):
        cross_cycle = {}
    extreme_state = brief.get("extreme_state")
    if not isinstance(extreme_state, dict):
        extreme_state = {}
    reading_notes = brief.get("reading_notes", {})
    context = {
        "title": brief.get("title", ""),
        "manifest": manifest,
        "macro": macro,
        "nature": nature,
        "veto": veto,
        "sector": sector,
        "risk_gates": risk_gates,
        "position_policy": position_policy,
        "cross_cycle": cross_cycle,
        "cross_cycle_summary": cross_cycle_summary(cross_cycle),
        "cross_cycle_table_rows": _format_cross_cycle_table(cross_cycle.get("table")),
        "cross_cycle_trajectory": _format_trajectory(cross_cycle.get("trajectory")),
        "cross_cycle_parts": _format_score_parts(cross_cycle),
        "cross_cycle_triggers": cross_cycle.get("upgrade_triggers", [])
        if isinstance(cross_cycle.get("upgrade_triggers"), list)
        else [],
        "extreme_state": extreme_state,
        "extreme_state_summary": extreme_state_summary(extreme_state),
        "extreme_window_rows": _format_extreme_windows(extreme_state),
        "risk_gate_rows": _format_risk_gates(risk_gates.get("gates", [])),
        "funding_health": _format_funding_health(nature.get("funding_health", {})),
        "macro_temperature_str": _value_text(macro.get("temperature")),
        "technical_temperature_str": _value_text(nature.get("technical_temperature")),
        "fund_flow_temperature_str": _value_text(nature.get("fund_flow_temperature")),
        "composite_delta_str": _value_text(nature.get("composite_delta")),
        "breadth_20d_str": _breadth_text(
            nature.get("breadth_20d"), nature.get("scored_industry_count")
        ),
        "breadth_60d_str": _breadth_text(
            nature.get("breadth_60d"), nature.get("scored_industry_count")
        ),
        "top5pct_str": _ratio_percent_text(_nested(veto, "top5pct", "value")),
        "crowded_share_str": _percent_text(veto.get("crowded_industry_share")),
        "margin_growth_20d_str": _ratio_percent_text(
            _nested(veto, "margin", "margin_balance_growth_20d")
        ),
        "crowded_industries": _format_rows(veto.get("crowded_industries", [])),
        "priority_industries": _format_rows(sector.get("priority", [])),
        "priority_excluded_industries": _format_rows(sector.get("priority_excluded", [])),
        "avoid_industries": _format_rows(sector.get("avoid", [])),
        "lagging_industries": _format_rows(sector.get("lagging", [])),
        "data_quality_notes": brief.get("data_quality_notes", []),
        "verified_facts": reading_notes.get("verified_facts", [])
        if isinstance(reading_notes, dict)
        else [],
        "mechanism_inferences": reading_notes.get("mechanism_inferences", [])
        if isinstance(reading_notes, dict)
        else [],
    }
    return ReportRenderer.get_instance().render("temperature/quant_brief.md.j2", context)


def _build_position_policy(
    macro: dict[str, Any],
    risk_gates: dict[str, Any],
) -> dict[str, Any]:
    temperature_band = macro.get("equity_position_band")
    risk_cap = risk_gates.get("max_position_band")
    effective_band = risk_cap or temperature_band
    if risk_cap:
        status = "risk_capped"
        reason = "风控闸门已生效，当前有效仓位服从防守上限。"
    else:
        status = "temperature_band"
        reason = "未触发硬性总闸门，当前有效仓位按综合温度档位执行。"
    return {
        "temperature_band": temperature_band,
        "risk_cap": risk_cap,
        "effective_band": effective_band,
        "status": status,
        "reason": reason,
    }
