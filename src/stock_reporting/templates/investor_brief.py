"""投资者简报模板。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from stock_reporting.engine.renderer import ReportRenderer
from stock_reporting.interpretation.investor_brief.interpretation import (
    evaluate_candidate_industries as _candidate_industries,
)
from stock_reporting.interpretation.investor_brief.interpretation import (
    evaluate_lagging_industries as _lagging_industries,
)
from stock_reporting.interpretation.investor_brief.interpretation import (
    evaluate_participation_decision as _participation_decision,
)
from stock_reporting.interpretation.investor_brief.interpretation import (
    evaluate_reading_notes as _reading_notes,
)
from stock_reporting.interpretation.investor_brief.interpretation import (
    evaluate_risk_industries as _risk_industries,
)

if TYPE_CHECKING:
    import polars as pl

    from stock_reporting.interpretation.investor_brief.config import InvestorBriefConfig


def build_brief_json(
    *,
    config: InvestorBriefConfig,
    manifest: dict[str, Any],
    market_scores: dict[str, Any],
    industry_scores: dict[str, Any],
    industry_panel: pl.DataFrame,
    market_facts: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """构造普通投资者可读简报的机器结构。"""
    dimensions = _dimension_temperatures(market_scores)
    participation = _participation_decision(market_scores, industry_scores, dimensions)
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "manifest": manifest,
        "participation": participation,
        "market_snapshot": {
            "composite_temperature": _composite_temperature(market_scores),
            "systemic_risk": market_scores.get("systemic_risk", {}),
            "external_risk": market_scores.get("external_risk", {}),
            "dimensions": dimensions,
        },
        "data_freshness": market_scores.get("data_freshness", {}),
        "data_watermarks": _data_watermarks(market_facts),
        "industry_snapshot": {
            "structure_health": industry_scores.get("structure_health", {}),
            "trend_diagnostics": industry_scores.get("trend_diagnostics", {}),
        },
        "candidate_industries": _candidate_industries(
            industry_panel,
            limit=config.max_candidate_industries,
        ),
        "risk_industries": _risk_industries(
            industry_panel,
            limit=config.max_risk_industries,
        ),
        "lagging_industries": _lagging_industries(
            industry_panel,
            limit=config.max_lagging_industries,
        ),
        "reading_notes": _reading_notes(market_scores, industry_scores),
    }


def render_brief_markdown(brief: dict[str, Any]) -> str:
    """渲染普通投资者简报 Markdown。"""
    manifest = brief["manifest"]
    participation = brief["participation"]
    market = brief["market_snapshot"]
    industry = brief["industry_snapshot"]

    def _format_table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "industry_name": r.get("industry_name") or "",
                "structure_score_str": _value_text(r.get("structure_score")),
                "return_20d_str": _value_text(r.get("return_20d")),
                "return_60d_str": _value_text(r.get("return_60d")),
                "crowding_temperature_str": _value_text(r.get("crowding_temperature")),
                "reason": r.get("reason") or "",
            }
            for r in rows
        ]

    context = {
        "title": brief.get("title", ""),
        "manifest": manifest,
        "participation": participation,
        "market": market,
        "external_risk": market.get("external_risk", {}),
        "market_composite_temp": _value_text(market.get("composite_temperature")),
        "structure_health_level": _structure_health_level(industry),
        "candidate_industries": _format_table_rows(brief.get("candidate_industries", [])),
        "risk_industries": _format_table_rows(brief.get("risk_industries", [])),
        "lagging_industries": _format_table_rows(brief.get("lagging_industries", [])),
        "data_quality_notes": _data_quality_notes(
            manifest,
            brief.get("data_freshness"),
            brief.get("data_watermarks"),
        ),
        "reading_notes": brief.get("reading_notes", []),
    }

    return ReportRenderer.get_instance().render("temperature/investor_brief.md.j2", context)


def _data_quality_notes(
    manifest: dict[str, Any],
    freshness: dict[str, Any] | None,
    watermarks: dict[str, str] | None = None,
) -> list[str]:
    as_of = str(manifest.get("as_of_date") or "基准日")
    notes = [
        f"行情基准日: {as_of}。",
        _funding_watermark_note(as_of, watermarks),
        "行业财报为季频慢变量底座，近20日边际预期以业绩预告、快报和研报上修为准。",
        "本简报只使用本地落盘事实，不引入外部未验证新闻或主观推断。",
    ]
    stale = (freshness or {}).get("stale_metrics") if isinstance(freshness, dict) else None
    if stale:
        parts = [
            (
                f"{item.get('metric_id')}（{item.get('dimension', '')}，"
                f"数据日期 {item.get('data_date', '未知')}）"
            )
            for item in stale
            if isinstance(item, dict) and item.get("metric_id")
        ]
        if parts:
            preview = "；".join(parts[:4])
            notes.append(
                "以下进入评分的指标数据日期已超过新鲜度阈值，温度合成中已按配置降权："
                f"{preview}{' 等。' if len(parts) > 4 else '。'}"
            )
    return notes


def _data_watermarks(facts: pl.DataFrame | None) -> dict[str, str]:
    """从市场温度事实中提取各数据集的实际最新日期。"""
    if facts is None or facts.is_empty():
        return {}
    required = {"category", "dataset", "metric_id", "status", "value_text"}
    if not required.issubset(facts.columns):
        return {}

    rows = (
        facts.filter(
            (facts["category"] == "data_watermark")
            & (facts["metric_id"] == "latest_trade_date")
            & (facts["status"] == "ok")
        )
        .select(["dataset", "value_text"])
        .to_dicts()
    )
    return {
        str(row["dataset"]): str(row["value_text"])
        for row in rows
        if row.get("dataset") and row.get("value_text")
    }


def _funding_watermark_note(as_of: str, watermarks: dict[str, str] | None) -> str:
    if not watermarks:
        return "未找到资金水位事实；主力资金流通常可能晚于行情日，以实际入库日期为准。"

    margin_date = watermarks.get("margin") or "未记录"
    moneyflow_date = watermarks.get("moneyflow") or "未记录"
    note = f"两融数据日期: {margin_date}；个股资金流数据日期: {moneyflow_date}。"
    try:
        as_of_date = date.fromisoformat(as_of)
    except ValueError:
        return note

    lagging = []
    for label, value in (("两融数据", margin_date), ("个股资金流数据", moneyflow_date)):
        try:
            if date.fromisoformat(value) < as_of_date:
                lagging.append(label)
        except ValueError:
            continue
    if lagging:
        note += f"{'、'.join(lagging)}较行情基准日滞后，以各自日期为准。"
    return note


def _industry_table(rows: list[dict[str, Any]], *, empty_text: str) -> list[str]:
    lines = [
        "",
        "| 行业 | 结构分 | 20日收益 | 60日收益 | 拥挤温度 | 理由 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    if not rows:
        return [*lines, f"| - | - | - | - | - | {empty_text} |"]
    for row in rows:
        lines.append(
            "| {name} | {score} | {ret20} | {ret60} | {crowding} | {reason} |".format(
                name=row.get("industry_name") or "",
                score=_value_text(row.get("structure_score")),
                ret20=_value_text(row.get("return_20d")),
                ret60=_value_text(row.get("return_60d")),
                crowding=_value_text(row.get("crowding_temperature")),
                reason=row.get("reason") or "",
            )
        )
    return lines


def _dimension_temperatures(scores: dict[str, Any]) -> dict[str, float | None]:
    dimensions = scores.get("dimensions", [])
    if not isinstance(dimensions, list):
        return {}
    return {
        str(item.get("dimension_id")): _as_float(item.get("temperature"))
        for item in dimensions
        if isinstance(item, dict) and item.get("dimension_id")
    }


def _composite_temperature(scores: dict[str, Any]) -> float | None:
    composite = scores.get("composite", {})
    if not isinstance(composite, dict):
        return None
    return _as_float(composite.get("temperature"))


def _structure_health_level(industry: dict[str, Any]) -> str:
    health = industry.get("structure_health", {})
    if not isinstance(health, dict):
        return "不可判定"
    return str(health.get("level") or "不可判定")


def _panel_rows(panel: pl.DataFrame) -> list[dict[str, Any]]:
    if panel.is_empty():
        return []
    return panel.to_dicts()


def _bullet_lines(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- 暂无。"]


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
