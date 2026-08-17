"""分析口径与质量报告的 Markdown 渲染。"""

from __future__ import annotations

from typing import Any


def render_quality_report_markdown(report: dict[str, Any]) -> str:
    """渲染面向人工阅读的口径与质量报告。"""
    policy = report["period_policy"]
    summary = report["summary"]
    lines = [
        f"# {report['title']}",
        "",
        f"- 基准日期: {report['as_of_date']}",
        f"- 质量状态: {_status_label(str(report['status']))}",
        f"- 主窗口: 最近 {policy['main_window']} 个{policy['window_unit']}",
        f"- 短线窗口: {_window_list(policy.get('short_windows', []))}",
        f"- 中期窗口: {_window_list(policy.get('medium_windows', []))}",
        f"- 主锚点: {policy['primary_data_source']}.{policy['primary_dataset']}",
    ]
    if policy.get("period_note"):
        lines.append(f"- 口径说明: {policy['period_note']}")
    lines.extend(
        [
            "",
            "## 约束结果",
            "",
            "- 数据集: "
            f"{summary['dataset_count']} 个，其中必需 {summary['required_dataset_count']} 个",
            f"- 硬错误: {summary['error_count']} 个",
            f"- 警告: {summary['warning_count']} 个",
            "",
            *_issue_lines(report["issues"]),
            "",
            "## 周期窗口",
            "",
            *_window_table(report["windows"]),
            "",
            "## 数据水位",
            "",
            *_watermark_table(report["watermarks"]),
            "",
            "## 口径规则",
            "",
            *_constraint_lines(report["constraints"]),
        ]
    )
    return "\n".join(lines) + "\n"


def _issue_lines(issues: list[dict[str, str]]) -> list[str]:
    if not issues:
        return ["- 未发现硬错误或质量警告。"]
    return [f"- [{_severity_label(item['severity'])}] {item['message']}" for item in issues]


def _window_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["无窗口事实。"]
    lines = [
        "| 窗口 | 覆盖区间 | 样本 | 状态 | 说明 |",
        "|---:|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {window} | {period} | {sample_size} | {status} | {note} |".format(
                window=row["window"],
                period=row["period"],
                sample_size=row["sample_size"],
                status=row["status"],
                note=row["note"],
            )
        )
    return lines


def _watermark_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["无数据水位配置。"]
    lines = [
        "| 数据集 | 频率 | 层级 | 必需 | 最新日期 | 滞后天数 | 阈值 | 状态 | 说明 |",
        "|---|---|---|---|---|---:|---:|---|---|",
    ]
    template = (
        "| {dataset} | {cadence} | {tier} | {required} | {latest} | {lag} | "
        "{max_lag} | {status} | {note} |"
    )
    for row in rows:
        latest = str(row["latest"] or "-")
        lag_days = "-" if row["lag_days"] is None else str(row["lag_days"])
        lines.append(
            template.format(
                dataset=f"{row['data_source']}.{row['dataset']}",
                cadence=row["cadence"],
                tier=row["quality_tier"],
                required="是" if row["required"] else "否",
                latest=latest,
                lag=lag_days,
                max_lag=row["max_lag_days"],
                status=row["status"],
                note=row["note"],
            )
        )
    return lines


def _constraint_lines(rows: list[dict[str, Any]]) -> list[str]:
    return [f"- [{row['level']}] {row['id']}: {row['rule']}" for row in rows]


def _window_list(values: list[int] | tuple[int, ...]) -> str:
    if not values:
        return "无"
    return ", ".join(f"{value} 日" for value in values)


def _status_label(status: str) -> str:
    return {
        "passed": "通过",
        "passed_with_warnings": "通过但有警告",
        "failed": "失败",
    }.get(status, status)


def _severity_label(severity: str) -> str:
    return {"error": "错误", "warning": "警告"}.get(severity, severity)
