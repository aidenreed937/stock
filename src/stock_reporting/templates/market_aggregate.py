"""全市场聚合监控报告模板。"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from stock_reporting.engine.renderer import ReportRenderer
from stock_reporting.templates.market_aggregate_trend import render_trend_section

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_aggregate.config import MarketAggregateConfig


def build_report_json(
    *,
    config: MarketAggregateConfig,
    manifest: dict[str, Any],
    snapshot: Any,
    freshness: str,
    age_seconds: float,
    quality_report: dict[str, Any],
    trend: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造机器可读聚合报告。"""
    metric_sections = build_metric_sections(config, snapshot)
    snapshot_payload = _snapshot_payload(snapshot)
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "manifest": manifest,
        "snapshot": snapshot_payload,
        "freshness": freshness,
        "age_seconds": age_seconds,
        "metric_sections": metric_sections,
        "quality": quality_report,
        "trend": trend or {},
    }


def build_quality_report(
    *,
    config: MarketAggregateConfig,
    manifest: dict[str, Any],
    snapshot: Any,
    freshness: str,
    age_seconds: float,
) -> dict[str, Any]:
    """根据覆盖率、状态和缓存新鲜度构造质量报告。"""
    issues: list[dict[str, str]] = []
    if snapshot.status == "partial":
        issues.append(
            {
                "severity": "warning",
                "message": (
                    f"上游返回不完整：{snapshot.returned_count}/{snapshot.reported_count}，"
                    f"覆盖率 {snapshot.coverage_ratio:.2%}。"
                ),
            }
        )
    if snapshot.coverage_ratio < config.quality.min_coverage_ratio:
        issues.append(
            {
                "severity": "error",
                "message": (
                    f"覆盖率 {snapshot.coverage_ratio:.2%} 低于质量阈值 "
                    f"{config.quality.min_coverage_ratio:.2%}。"
                ),
            }
        )
    if freshness == "stale":
        issues.append(
            {
                "severity": "warning",
                "message": f"使用 {age_seconds:.1f} 秒前的缓存快照。",
            }
        )
    elif freshness == "expired":
        issues.append(
            {
                "severity": "error",
                "message": f"缓存快照已超过最大年龄，当前年龄 {age_seconds:.1f} 秒。",
            }
        )
    unknown_metrics = [
        row["label"]
        for section in build_metric_sections(config, snapshot)
        for row in section["rows"]
        if not row["available"]
    ]
    if unknown_metrics:
        issues.append(
            {
                "severity": "warning",
                "message": f"配置中的指标暂无可用字段：{'、'.join(unknown_metrics)}。",
            }
        )
    error_count = sum(item["severity"] == "error" for item in issues)
    warning_count = sum(item["severity"] == "warning" for item in issues)
    status = "failed" if error_count else "passed_with_warnings" if warning_count else "passed"
    return {
        "title": f"{config.title}质量报告",
        "status": status,
        "as_of_date": snapshot.quote_date.isoformat(),
        "manifest": manifest,
        "summary": {
            "error_count": error_count,
            "warning_count": warning_count,
            "reported_count": snapshot.reported_count,
            "returned_count": snapshot.returned_count,
            "coverage_ratio": snapshot.coverage_ratio,
            "freshness": freshness,
            "age_seconds": age_seconds,
        },
        "issues": issues,
        "constraints": [
            {
                "level": "hard",
                "id": "coverage",
                "rule": f"覆盖率应达到配置阈值 {config.quality.min_coverage_ratio:.2%}。",
            },
            {
                "level": "soft",
                "id": "freshness",
                "rule": (
                    f"缓存 {config.cache.fresh_ttl_seconds:.0f} 秒内为 fresh，"
                    f"超过 {config.cache.max_age_seconds:.0f} 秒为 expired。"
                ),
            },
            {
                "level": "scope",
                "id": "scope",
                "rule": "只解释全市场聚合摘要，不将其视为逐标的全市场快照。",
            },
        ],
    }


def render_report_markdown(
    *,
    config: MarketAggregateConfig,
    manifest: dict[str, Any],
    snapshot: Any,
    freshness: str,
    age_seconds: float,
    quality_report: dict[str, Any],
    trend: dict[str, Any] | None = None,
) -> str:
    """按配置模板渲染机器/审计版 Markdown 报告。"""
    return ReportRenderer.get_instance().render(
        config.report.report_template,
        _context(
            config=config,
            manifest=manifest,
            snapshot=snapshot,
            freshness=freshness,
            age_seconds=age_seconds,
            quality_report=quality_report,
            trend=trend,
        ),
    )


def render_human_report_markdown(
    *,
    config: MarketAggregateConfig,
    manifest: dict[str, Any],
    snapshot: Any,
    freshness: str,
    age_seconds: float,
    quality_report: dict[str, Any],
    trend: dict[str, Any] | None = None,
) -> str:
    """按配置模板渲染人工阅读版 Markdown 报告。"""
    context = _context(
        config=config,
        manifest=manifest,
        snapshot=snapshot,
        freshness=freshness,
        age_seconds=age_seconds,
        quality_report=quality_report,
        trend=trend,
    )
    context["headline"] = _headline(snapshot, freshness)
    context["reading_notes"] = _reading_notes(snapshot, freshness)
    return ReportRenderer.get_instance().render(config.report.human_template, context)


def render_table_markdown(
    *,
    config: MarketAggregateConfig,
    manifest: dict[str, Any],
    snapshot: Any,
    freshness: str,
    age_seconds: float,
    quality_report: dict[str, Any],
) -> str:
    """按配置模板渲染终端友好的聚合指标表。"""
    context = _context(
        config=config,
        manifest=manifest,
        snapshot=snapshot,
        freshness=freshness,
        age_seconds=age_seconds,
        quality_report=quality_report,
    )
    context["rows"] = [row for section in context["metric_sections"] for row in section["rows"]]
    context["show_header"] = True
    return ReportRenderer.get_instance().render(config.report.table_template, context)


def render_quality_report_markdown(
    *,
    config: MarketAggregateConfig,
    quality_report: dict[str, Any],
) -> str:
    """按配置模板渲染质量报告。"""
    return ReportRenderer.get_instance().render(
        config.report.quality_template,
        {"report": quality_report, "config": config},
    )


def build_metric_sections(config: MarketAggregateConfig, snapshot: Any) -> list[dict[str, Any]]:
    """按 YAML 中的顺序和分组构造指标行。"""
    sections: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for metric in config.report.metrics:
        if not metric.enabled:
            continue
        value, available = _metric_value(metric.metric_id, snapshot)
        sections.setdefault(metric.section, []).append(
            {
                "metric_id": metric.metric_id,
                "label": metric.label,
                "value": value,
                "available": available,
                "note": metric.note,
            }
        )
    return [{"title": title, "rows": rows} for title, rows in sections.items()]


def _context(
    *,
    config: MarketAggregateConfig,
    manifest: dict[str, Any],
    snapshot: Any,
    freshness: str,
    age_seconds: float,
    quality_report: dict[str, Any],
    trend: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "title": config.title,
        "manifest": manifest,
        "received_at": _format_received_at(manifest.get("received_at")),
        "snapshot": snapshot,
        "status": snapshot.status,
        "freshness": freshness,
        "age_seconds": age_seconds,
        "coverage_text": (
            f"{snapshot.returned_count}/{snapshot.reported_count} （{snapshot.coverage_ratio:.2%}）"
        ),
        "metric_sections": build_metric_sections(config, snapshot),
        "table_template": config.report.table_template,
        "show_header": False,
        "limitations": list(config.report.limitations),
        "quality_report": quality_report,
        "trend_section": render_trend_section(trend),
    }


def _format_received_at(value: Any) -> str:
    if value is None:
        return "-"
    return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M:%S")


def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
    payload = cast("dict[str, Any]", snapshot.model_dump(mode="json"))
    payload["quote_date"] = snapshot.quote_date.isoformat()
    return payload


def _metric_value(metric_id: str, snapshot: Any) -> tuple[str, bool]:
    if metric_id == "coverage":
        return (
            f"{snapshot.returned_count}/{snapshot.reported_count} ({snapshot.coverage_ratio:.2%})",
            True,
        )
    if metric_id == "breadth_counts":
        return f"{snapshot.advance_count} / {snapshot.decline_count} / {snapshot.flat_count}", True
    if metric_id == "breadth_shares":
        return f"{_share(snapshot.advance_share)} / {_share(snapshot.decline_share)}", True
    if metric_id == "advance_decline_ratio":
        return _ratio(snapshot.advance_decline_ratio), snapshot.advance_decline_ratio is not None
    if metric_id == "strong_move_counts":
        return (
            f"{snapshot.strong_up_count} / {snapshot.strong_down_count} "
            f"（±{snapshot.strong_up_threshold_pct:.1f}%）",
            True,
        )
    if metric_id == "change_distribution":
        return (
            f"{_pct(snapshot.pct_change_p25)} / {_pct(snapshot.median_pct_change)} "
            f"/ {_pct(snapshot.pct_change_p75)}",
            any(
                value is not None
                for value in (
                    snapshot.pct_change_p25,
                    snapshot.median_pct_change,
                    snapshot.pct_change_p75,
                )
            ),
        )
    if metric_id == "weighted_pct_change":
        return _pct(snapshot.weighted_pct_change), snapshot.weighted_pct_change is not None
    if metric_id == "amount_total":
        return _money(snapshot.amount_total_yuan), snapshot.amount_total_yuan is not None
    if metric_id == "market_value":
        return (
            f"{_money(snapshot.total_market_value_yuan)} / "
            f"{_money(snapshot.free_float_market_value_yuan)}",
            any(
                value is not None
                for value in (
                    snapshot.total_market_value_yuan,
                    snapshot.free_float_market_value_yuan,
                )
            ),
        )
    if metric_id == "free_float_turnover":
        return _pct(snapshot.free_float_turnover_pct), snapshot.free_float_turnover_pct is not None
    if metric_id == "amount_top_5pct_share":
        return _share(snapshot.amount_top_5pct_share), snapshot.amount_top_5pct_share is not None
    return "-", False


def _headline(snapshot: Any, freshness: str) -> str:
    if freshness in {"stale", "expired"}:
        return f"当前报告使用{freshness}缓存，先确认数据新鲜度，再解读市场状态。"
    if snapshot.status == "partial":
        return "当前快照覆盖不完整，市场广度与成交统计应按覆盖率折价解读。"
    if snapshot.advance_share is not None and snapshot.advance_share >= 0.6:
        return "市场上涨扩散占优，短线广度偏强；仍需结合成交额和集中度判断参与质量。"
    if snapshot.decline_share is not None and snapshot.decline_share >= 0.6:
        return "市场下跌扩散占优，短线风险偏弱；应关注成交额和集中度是否同步恶化。"
    return "市场涨跌扩散处于中性区间，暂以结构和成交质量观察为主。"


def _reading_notes(snapshot: Any, freshness: str) -> list[str]:
    notes = [
        "上涨/下跌/平盘统计只覆盖本次返回且具有涨跌幅字段的标的。",
        "成交额加权涨跌幅反映成交集中标的对整体交易结果的影响，不等同于指数涨跌幅。",
    ]
    if snapshot.amount_top_5pct_share is not None and snapshot.amount_top_5pct_share >= 0.5:
        notes.append("成交额前 5% 集中度较高，表明市场交易可能由少数高成交标的主导。")
    if freshness == "fresh":
        notes.append("当前快照处于 fresh 状态，可作为本次盘中观察的即时截面。")
    return notes


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}%"


def _share(value: float | None) -> str:
    return "-" if value is None else f"{value:.2%}"


def _ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}万亿"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.0f}元"


__all__ = [
    "build_metric_sections",
    "build_quality_report",
    "build_report_json",
    "render_human_report_markdown",
    "render_quality_report_markdown",
    "render_report_markdown",
    "render_table_markdown",
]
