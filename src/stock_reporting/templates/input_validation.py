"""报告模板输入契约与缺失数据提示。"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

import polars as pl

INDUSTRY_FACT_COLUMNS = frozenset(
    {"category", "data_source", "dataset", "value_text", "status", "note"}
)
INDUSTRY_PANEL_COLUMNS = frozenset(
    {
        "industry_code",
        "structure_score",
        "return_20d",
        "return_60d",
        "tcr",
        "money_net_inflow_share_20d",
    }
)
MARKET_FACT_COLUMNS = frozenset(
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
    }
)


def missing_columns(frame: pl.DataFrame, required: Collection[str]) -> list[str]:
    return [] if frame.is_empty() else sorted(set(required) - set(frame.columns))


def summarize_facts(frame: pl.DataFrame, required: Collection[str]) -> dict[str, Any]:
    if frame.is_empty():
        return {"rows": 0, "by_status": {}, "by_category": {}}
    missing = missing_columns(frame, required)
    if missing:
        return {
            "rows": frame.height,
            "by_status": {},
            "by_category": {},
            "missing_columns": missing,
        }
    return {
        "rows": frame.height,
        "by_status": _count_by(frame, "status"),
        "by_category": _count_by(frame, "category"),
    }


def fact_availability(frame: pl.DataFrame, required: Collection[str]) -> dict[str, Any]:
    missing = missing_columns(frame, required)
    return {"status": "unavailable" if missing else "available", "missing_columns": missing}


def industry_availability(facts: pl.DataFrame, panel: pl.DataFrame) -> dict[str, Any]:
    missing_facts = missing_columns(facts, INDUSTRY_FACT_COLUMNS)
    missing_panel = missing_columns(panel, INDUSTRY_PANEL_COLUMNS)
    return {
        "status": "unavailable" if missing_facts or missing_panel else "available",
        "missing_fact_columns": missing_facts,
        "missing_panel_columns": missing_panel,
    }


def industry_unavailable(title: str, facts: pl.DataFrame, panel: pl.DataFrame) -> str | None:
    missing_facts = missing_columns(facts, INDUSTRY_FACT_COLUMNS)
    missing_panel = missing_columns(panel, INDUSTRY_PANEL_COLUMNS)
    if not missing_facts and not missing_panel:
        return None
    details = []
    if missing_facts:
        details.append(f"事实表缺少必需列：{', '.join(missing_facts)}")
    if missing_panel:
        details.append(f"行业面板缺少必需列：{', '.join(missing_panel)}")
    return f"# {title}\n\n## 数据不可用\n\n{'；'.join(details)}。\n请补齐输入数据后重新生成报告。"


def market_unavailable(title: str, facts: pl.DataFrame) -> str | None:
    missing = missing_columns(facts, MARKET_FACT_COLUMNS)
    if not missing:
        return None
    return (
        f"# {title}\n\n## 数据不可用\n\n事实表缺少必需列：{', '.join(missing)}。\n"
        "请补齐事实层输入后重新生成报告。"
    )


def _count_by(frame: pl.DataFrame, column: str) -> dict[str, int]:
    return {
        str(row[column]): int(row["len"])
        for row in frame.group_by(column).len().sort(column).to_dicts()
    }
