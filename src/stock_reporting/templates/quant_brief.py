"""量化投研简报结构化输出与 Markdown 模板。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stock_reporting.engine.renderer import ReportRenderer
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
) -> dict[str, Any]:
    """构造量化投研简报机器结构。"""
    macro = evaluate_macro(config, market_scores)
    nature = evaluate_nature(config, market_scores, industry_scores, market_facts)
    veto = evaluate_veto(config, market_scores, industry_scores, industry_panel, market_facts)
    sector = evaluate_sector(config, industry_panel)
    risk_gates = evaluate_risk_gates(
        config,
        market_scores,
        industry_scores,
        industry_panel,
        market_facts,
    )
    position_policy = _build_position_policy(macro, risk_gates)
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


def _format_rows(rows: object) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "industry_name": str(row.get("industry_name") or row.get("industry_code") or ""),
                "structure_score": _value_text(row.get("structure_score")),
                "return_20d": _percent_text(row.get("return_20d")),
                "return_60d": _percent_text(row.get("return_60d")),
                "crowding_temperature": _value_text(row.get("crowding_temperature")),
                "tcr": _percent_text(row.get("tcr")),
                "fund_flow_score": _value_text(row.get("fund_flow_score")),
                "tags": str(row.get("tags") or ""),
                "reason": str(row.get("reason") or ""),
            }
        )
    return result


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


def _format_risk_gates(gates: object) -> list[dict[str, str]]:
    if not isinstance(gates, list):
        return []
    result = []
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        result.append(
            {
                "title": str(gate.get("title") or ""),
                "status": str(gate.get("status_label") or gate.get("status") or ""),
                "facts": str(gate.get("facts_text") or "-"),
                "message": str(gate.get("message") or ""),
                "action": str(gate.get("action") or ""),
            }
        )
    return result


def _format_funding_health(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {
            "status": "资料不足",
            "main_flow_label": "主力大单净流入占比",
            "main_flow": "-",
            "cumulative_flow": "-",
            "super_large_flow": "-",
            "margin_buy": "-",
            "margin_growth20": "-",
            "margin_growth60": "-",
            "margin_penetration": "-",
            "margin_penetration_percentile": "-",
            "action": "补齐资金与两融事实。",
            "note": "-",
        }
    return {
        "status": str(value.get("status_label") or value.get("status") or "资料不足"),
        "main_flow_label": (
            "主力大单净流入占比"
            if value.get("main_large_order_net_inflow_share_source")
            == "main_large_order_net_inflow_share"
            else "主力净流入代理占比"
        ),
        "main_flow": _ratio_percent_text(value.get("main_large_order_net_inflow_share")),
        "cumulative_flow": _ratio_percent_text(value.get("main_money_net_inflow_share_20d_cum")),
        "super_large_flow": _ratio_percent_text(value.get("super_large_net_inflow_share")),
        "margin_buy": _ratio_percent_text(value.get("margin_buy_share")),
        "margin_growth20": _ratio_percent_text(value.get("margin_balance_growth_20d")),
        "margin_growth60": _ratio_percent_text(value.get("margin_balance_growth_60d")),
        "margin_penetration": _ratio_percent_text(value.get("margin_penetration")),
        "margin_penetration_percentile": _value_text(
            value.get("margin_penetration_percentile_1250d")
        ),
        "action": str(value.get("action") or "-"),
        "note": str(value.get("note") or "-"),
    }


def _breadth_text(count: object, total: object) -> str:
    count_text = _value_text(count)
    total_text = _value_text(total)
    return "-" if count_text == "-" else f"{count_text}/{total_text}"


def _percent_text(value: object) -> str:
    numeric = _as_float(value)
    return "-" if numeric is None else f"{numeric:.2f}%"


def _ratio_percent_text(value: object) -> str:
    numeric = _as_float(value)
    return "-" if numeric is None else f"{numeric * 100:.2f}%"


def _value_text(value: object) -> str:
    numeric = _as_float(value)
    return "-" if numeric is None else f"{numeric:.2f}"


def _nested(value: object, first: str, second: str) -> object:
    if not isinstance(value, dict):
        return None
    return value.get(first, {}).get(second) if isinstance(value.get(first), dict) else None


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["build_quant_brief_json", "render_quant_brief_markdown"]
