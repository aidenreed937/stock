"""报告模板的数据可用性与领域观察项渲染辅助。"""

from __future__ import annotations

from typing import Any

import polars as pl


def _missing_columns(frame: pl.DataFrame, required: set[str]) -> list[str]:
    if frame.is_empty():
        return []
    return sorted(required - set(frame.columns))


def industry_missing_fact_columns(facts: pl.DataFrame) -> list[str]:
    return _missing_columns(
        facts, {"category", "data_source", "dataset", "value_text", "status", "note"}
    )


def industry_missing_panel_columns(panel: pl.DataFrame) -> list[str]:
    return _missing_columns(
        panel,
        {
            "industry_code",
            "structure_score",
            "return_20d",
            "return_60d",
            "tcr",
            "money_net_inflow_share_20d",
        },
    )


def industry_availability(facts: pl.DataFrame, panel: pl.DataFrame) -> dict[str, Any]:
    missing_facts = industry_missing_fact_columns(facts)
    missing_panel = industry_missing_panel_columns(panel)
    return {
        "status": "unavailable" if missing_facts or missing_panel else "available",
        "missing_fact_columns": missing_facts,
        "missing_panel_columns": missing_panel,
    }


def industry_unavailable_report(title: str, facts: pl.DataFrame, panel: pl.DataFrame) -> str | None:
    missing_facts = industry_missing_fact_columns(facts)
    missing_panel = industry_missing_panel_columns(panel)
    if not missing_facts and not missing_panel:
        return None
    details: list[str] = []
    if missing_facts:
        details.append(f"事实表缺少必需列：{', '.join(missing_facts)}")
    if missing_panel:
        details.append(f"行业面板缺少必需列：{', '.join(missing_panel)}")
    return (
        f"# {title}\n\n## 数据不可用\n\n"
        + "；".join(details)
        + "。\n请补齐输入数据后重新生成报告。"
    )


def market_missing_fact_columns(facts: pl.DataFrame) -> list[str]:
    return _missing_columns(
        facts,
        {
            "category",
            "dimension",
            "data_source",
            "dataset",
            "metric_id",
            "value_float",
            "value_text",
            "sample_size",
            "status",
            "note",
        },
    )


def market_availability(facts: pl.DataFrame) -> dict[str, Any]:
    missing = market_missing_fact_columns(facts)
    return {"status": "unavailable" if missing else "available", "missing_columns": missing}


def market_unavailable_report(title: str, facts: pl.DataFrame) -> str | None:
    missing = market_missing_fact_columns(facts)
    if not missing:
        return None
    return (
        f"# {title}\n\n"
        "## 数据不可用\n\n"
        f"事实表缺少必需列：{', '.join(missing)}。\n"
        "请补齐事实层输入后重新生成报告。"
    )


def summarize_fact_frame(facts: pl.DataFrame, missing_columns: list[str]) -> dict[str, Any]:
    if facts.is_empty():
        return {"rows": 0, "by_status": {}, "by_category": {}}
    if missing_columns:
        return {
            "rows": facts.height,
            "by_status": {},
            "by_category": {},
            "missing_columns": missing_columns,
        }
    return {
        "rows": facts.height,
        "by_status": _count_by(facts, "status"),
        "by_category": _count_by(facts, "category"),
    }


def industry_summarize_facts(facts: pl.DataFrame) -> dict[str, Any]:
    return summarize_fact_frame(facts, industry_missing_fact_columns(facts))


def market_summarize_facts(facts: pl.DataFrame) -> dict[str, Any]:
    return summarize_fact_frame(facts, market_missing_fact_columns(facts))


def domain_observation_lines(facts: pl.DataFrame) -> list[str]:
    observations = facts.filter(pl.col("category") == "domain_observation").sort(
        ["dimension", "metric_id"]
    )
    if observations.is_empty():
        return []
    lines = [
        "",
        "## 领域 Mart 观察项",
        "",
        "| 维度 | 观察项 | 数值 | 单位 | 样本数 | 状态 | 说明 |",
        "|---|---|---:|---|---:|---|---|",
    ]
    for row in observations.to_dicts():
        value = "" if row["value_float"] is None else f"{float(row['value_float']):.6g}"
        sample_size = "" if row["sample_size"] is None else str(row["sample_size"])
        lines.append(
            "| {dimension} | {metric} | {value} | {unit} | {sample_size} | {status} | {note} |".format(
                dimension=row["dimension"],
                metric=row["metric_id"],
                value=value,
                unit=row["unit"],
                sample_size=sample_size,
                status=row["status"],
                note=row["note"],
            )
        )
    return lines


def _count_by(facts: pl.DataFrame, column: str) -> dict[str, int]:
    return {
        str(row[column]): int(row["len"])
        for row in facts.group_by(column).len().sort(column).to_dicts()
    }


__all__ = [
    "domain_observation_lines",
    "industry_availability",
    "industry_missing_fact_columns",
    "industry_missing_panel_columns",
    "industry_summarize_facts",
    "industry_unavailable_report",
    "market_availability",
    "market_missing_fact_columns",
    "market_summarize_facts",
    "market_unavailable_report",
    "summarize_fact_frame",
]
