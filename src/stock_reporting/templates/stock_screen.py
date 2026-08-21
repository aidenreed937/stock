"""个股排雷 Markdown 与 JSON 报告。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_reporting.interpretation.stock_screen.config import StockScreenConfig


def build_report_json(
    *,
    config: StockScreenConfig,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    tables: dict[str, pl.DataFrame],
) -> dict[str, Any]:
    """构造排雷报告 JSON 摘要。"""
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "as_of_date": manifest["as_of_date"],
        "summary": summary,
        "top_excluded": _rows(tables.get("excluded"), limit=20),
        "top_warned": _rows(tables.get("warned"), limit=config.output.max_warn_rows),
        "top_passed": _rows(tables.get("passed"), limit=config.output.top_passed),
    }


def render_report_markdown(
    *,
    config: StockScreenConfig,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    tables: dict[str, pl.DataFrame],
) -> str:
    """渲染面向人工阅读的排雷摘要。"""
    lines = [
        f"# {config.title}",
        "",
        f"- 基准日期: {manifest['as_of_date']}",
        f"- 样本总数: {summary['population_size']}",
        f"- 硬性剔除: {summary['excluded_count']}",
        f"- 黄牌预警: {summary['warned_count']}",
        f"- 通过: {summary['passed_count']}",
        "",
        "## 硬性剔除清单（前 20 条）",
        "",
        *_table_lines(tables.get("excluded"), limit=20),
        "",
        "## 黄牌预警清单",
        "",
        *_table_lines(tables.get("warned"), limit=config.output.max_warn_rows),
        "",
        f"## 通过名单（前 {config.output.top_passed} 条）",
        "",
        *_table_lines(tables.get("passed"), limit=config.output.top_passed),
        "",
        "## 数据缺口与限制",
        "",
        *_gap_lines(summary),
    ]
    return "\n".join(lines) + "\n"


def render_quality_report_markdown(report: dict[str, Any]) -> str:
    """渲染排雷质量报告。"""
    summary = report["summary"]
    lines = [
        f"# {report['title']}",
        "",
        f"- 基准日期: {report['as_of_date']}",
        f"- 质量状态: {report['status']}",
        f"- 数据集: {summary['dataset_count']} 个",
        f"- 数据错误: {summary['error_count']} 个",
        f"- 数据警告: {summary['warning_count']} 个",
        "",
        "## 数据集状态",
        "",
        "| 数据集 | 状态 | 最新日期 | 说明 |",
        "|---|---|---|---|",
    ]
    for row in report.get("watermarks", []):
        lines.append(
            f"| {row['data_source']}.{row['dataset']} | {row['status']} | "
            f"{row.get('latest') or '-'} | {row.get('note') or ''} |"
        )
    lines.extend(["", "## 质量问题", ""])
    issues = report.get("issues", [])
    lines.extend(
        [f"- [{item['severity']}] {item['message']}" for item in issues]
        or ["- 未发现数据质量问题。"]
    )
    return "\n".join(lines) + "\n"


def _table_lines(frame: pl.DataFrame | None, *, limit: int) -> list[str]:
    if frame is None or frame.is_empty():
        return ["暂无记录。"]
    rows = frame.head(limit).to_dicts()
    lines = [
        "| 代码 | 名称 | 级别 | 命中规则 | 理由 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        reasons = "；".join(str(item) for item in row.get("reasons") or [])
        lines.append(
            f"| {row.get('symbol', '')} | {row.get('name') or '-'} | {row.get('level', '')} | "
            f"{','.join(str(item) for item in row.get('rule_ids') or []) or '-'} | {reasons or '-'} |"
        )
    return lines


def _gap_lines(summary: dict[str, Any]) -> list[str]:
    gaps = summary.get("data_gaps", [])
    missing = summary.get("missing_gates", [])
    lines = [
        f"- 数据集缺口: {gap['data_source']}.{gap['dataset']}（{gap['status']}）{gap.get('note', '')}"
        for gap in gaps
    ]
    lines.extend(
        f"- 规则限制: {item['rule_id']}（{item.get('status', 'disabled')}）{item.get('note', '')}"
        for item in missing
    )
    return lines or ["- 未记录数据缺口。"]


def _rows(frame: pl.DataFrame | None, *, limit: int) -> list[dict[str, Any]]:
    if frame is None or frame.is_empty():
        return []
    return frame.head(limit).to_dicts()


__all__ = [
    "build_report_json",
    "render_quality_report_markdown",
    "render_report_markdown",
]
