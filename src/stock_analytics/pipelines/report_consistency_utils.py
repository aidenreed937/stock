"""报告一致性校验的文件读取与数值辅助函数。"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

import polars as pl

from stock_analytics.pipelines.artifact_reader import select_artifact_run_dir
from stock_analytics.pipelines.report_consistency_contracts import ArtifactBundle


def _latest_run_dir(
    root: Path,
    as_of_date: str,
    *,
    run_class: str | None = None,
) -> Path | None:
    return select_artifact_run_dir(root, as_of_date=as_of_date, expected_run_class=run_class)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return cast("dict[str, Any]", payload)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _markdown_paths(bundle: ArtifactBundle) -> tuple[Path, ...]:
    names = {
        "market_temperature": ("report.md", "human_report.md", "quality_report.md"),
        "industry_structure": ("report.md", "human_report.md", "quality_report.md"),
        "investor_brief": ("brief_report.md",),
        "quant_brief": ("brief_report.md",),
    }
    return tuple(bundle.run_dir / name for name in names[bundle.name])


def _number_variants(value: Any) -> set[str]:
    number = _to_float(value)
    if not _is_finite(number):
        return set()
    return {str(value), f"{number:.2f}", f"{number:.1f}", f"{number:.0f}"}


def _numbers_equal(left: Any, right: Any, *, precision: int = 2) -> bool:
    left_number = _to_float(left)
    right_number = _to_float(right)
    if not _is_finite(left_number) or not _is_finite(right_number):
        return bool(left == right)
    return round(left_number, precision) == round(right_number, precision)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _is_finite(value: float) -> bool:
    return math.isfinite(value)


def _panel_by_name(panel: pl.DataFrame) -> dict[str, dict[str, Any]]:
    if "industry_name" not in panel.columns:
        return {}
    return {str(row["industry_name"]): row for row in panel.to_dicts()}


def _watermark_dates(facts: pl.DataFrame) -> dict[str, str]:
    if facts.is_empty():
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


def _metric_value(facts: pl.DataFrame, metric_id: str) -> float | None:
    if facts.is_empty() or not {"category", "metric_id", "status", "value_float"}.issubset(
        facts.columns
    ):
        return None
    frame = facts.filter(
        (facts["category"] == "metric_value")
        & (facts["metric_id"] == metric_id)
        & (facts["status"] == "ok")
    )
    if frame.is_empty():
        return None
    value = frame["value_float"][-1]
    return _to_float(value) if math.isfinite(_to_float(value)) else None


def _in_range(value: str, start: str | None, end: str | None) -> bool:
    return (start is None or value >= start) and (end is None or value <= end)
