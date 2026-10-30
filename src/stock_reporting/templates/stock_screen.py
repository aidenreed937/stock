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
    warn_limit = config.output.max_warn_rows or 500
    passed_limit = config.output.top_passed or 100
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "as_of_date": manifest["as_of_date"],
        "summary": summary,
        "top_excluded": _rows(tables.get("excluded"), limit=20),
        "top_warned": _rows(tables.get("warned"), limit=warn_limit),
        "top_passed": _rows(tables.get("passed"), limit=passed_limit),
        "top_scored": _rows(tables.get("scored"), limit=passed_limit),
    }


def render_report_markdown(
    *,
    config: StockScreenConfig,
    manifest: dict[str, Any],
    summary: dict[str, Any],
    tables: dict[str, pl.DataFrame],
) -> str:
    """渲染面向人工阅读的排雷摘要（优先展示评分排名前 100）。"""
    scored = tables.get("scored")
    has_scoring = scored is not None and not scored.is_empty()
    lines = [
        f"# {config.title}",
        "",
        f"- 基准日期: {manifest['as_of_date']}",
        f"- 样本总数: {summary['population_size']}",
        f"- 硬性剔除: {summary['excluded_count']} 只（详见 `excluded.csv`）",
        f"- 黄牌预警: {summary['warned_count']} 只（详见 `warned.csv`）",
        f"- 通过排雷: {summary['passed_count']} 只（详见 `passed.csv`）",
    ]
    if has_scoring:
        lines.extend(
            [
                f"- 评分覆盖: {summary.get('scored_top_count', 0)} 只",
                f"- 评分中位数: {summary.get('scored_median', '-')}",
            ]
        )

    # 优先展示：评分排名前 100
    if has_scoring and scored is not None:
        passed_limit = config.output.top_passed or 100
        display_top = min(passed_limit, scored.height)
        lines.extend(
            [
                "",
                f"## 评分排名前 {display_top}（综合评分越高越优）",
                "",
                "> 说明：综合评分 (100) = 质量 Quality (40%) + 估值 Value (30%) + 动量 Momentum (20%) + 规模 Size (10%)，在申万行业内分层百分位对齐。",
                "",
                *_scored_table_lines(scored, limit=passed_limit),
            ]
        )

    # 精简抽样展示排雷风险清单（前 10 条）
    lines.extend(
        [
            "",
            f"## 黄牌预警抽样（前 10 条，全量共 {summary['warned_count']} 条见 `warned.csv`）",
            "",
            *_table_lines(tables.get("warned"), limit=10),
            "",
            f"## 硬性剔除抽样（前 10 条，全量共 {summary['excluded_count']} 条见 `excluded.csv`）",
            "",
            *_table_lines(tables.get("excluded"), limit=10),
            "",
            "## 数据缺口与限制",
            "",
            *_gap_lines(summary),
        ]
    )
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


def _scored_table_lines(frame: pl.DataFrame, *, limit: int) -> list[str]:
    if frame.is_empty():
        return ["暂无记录。"]
    rows = frame.head(limit).to_dicts()
    has_dims = all(f"dim_{k}" in frame.columns for k in ("quality", "value", "momentum", "size"))
    if has_dims:
        lines = [
            "| 排名 | 代码 | 名称 | 申万行业 | 综合评分 | 质量分 | 估值分 | 动量分 | 规模分 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            score = row.get("composite_score")
            score_text = f"{score:.1f}" if score is not None else "-"
            q = row.get("dim_quality")
            v = row.get("dim_value")
            m = row.get("dim_momentum")
            s = row.get("dim_size")
            industry = row.get("l2_name") or row.get("l1_name") or row.get("industry") or "-"
            lines.append(
                f"| {row.get('rank', '-')} | {row.get('symbol', '')} | {row.get('name') or '-'} | "
                f"{industry} | {score_text} | "
                f"{f'{q:.1f}' if q is not None else '-'} | "
                f"{f'{v:.1f}' if v is not None else '-'} | "
                f"{f'{m:.1f}' if m is not None else '-'} | "
                f"{f'{s:.1f}' if s is not None else '-'} |"
            )
        return lines
    lines = [
        "| 排名 | 代码 | 名称 | 行业 | 综合评分 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        score = row.get("composite_score")
        score_text = f"{score:.1f}" if score is not None else "-"
        industry = row.get("l2_name") or row.get("l1_name") or row.get("industry") or "-"
        lines.append(
            f"| {row.get('rank', '-')} | {row.get('symbol', '')} | {row.get('name') or '-'} | "
            f"{industry} | {score_text} |"
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
