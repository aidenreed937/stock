"""个股排雷 manifest 与数据质量摘要。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.manifest import build_manifest_base
from stock_analytics.pipelines.stock_screen.artifacts import StockScreenRunPaths
from stock_analytics.pipelines.stock_screen.sources import StockScreenSources
from stock_reporting.interpretation.stock_screen.config import StockScreenConfig


def build_manifest(
    config: StockScreenConfig,
    as_of_date: date,
    paths: StockScreenRunPaths,
    scores: dict[str, Any],
    *,
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    """构造一次排雷运行的 manifest。"""
    manifest = build_manifest_base(
        artifact_type="stock_screen",
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=paths.root,
        config_path=config_path,
    )
    manifest.update(
        {
            "rule_version": scores["rule_version"],
            "population_size": scores["population_size"],
            "data_gaps": scores["data_gaps"],
            "missing_gates": scores["missing_gates"],
            "files": {
                "manifest": paths.manifest.name,
                "excluded": paths.excluded.name,
                "warned": paths.warned.name,
                "passed": paths.passed.name,
                "scores": paths.scores.name,
                "screen_report": paths.report_md.name,
                "screen_report_json": paths.report_json.name,
                "quality_report": paths.quality_report_md.name,
                "quality_report_json": paths.quality_report_json.name,
            },
            "optional_files": {"scored": paths.scored.name},
        }
    )
    return manifest


def build_quality_report(
    config: StockScreenConfig,
    as_of_date: date,
    sources: StockScreenSources,
    scores: dict[str, Any],
) -> dict[str, Any]:
    """构造数据集水位、缺口和质量状态报告。"""
    watermarks = []
    issues = []
    for item in config.datasets:
        frame = sources.get(item.dataset)
        latest = latest_date(frame, item.date_column)
        status = "disabled" if not item.enabled else ("ok" if not frame.is_empty() else "missing")
        if status == "missing":
            severity = "error" if item.required else "warning"
            issues.append(
                {
                    "severity": severity,
                    "id": "dataset_unavailable",
                    "message": f"{item.data_source}.{item.dataset} 不可用。",
                }
            )
        watermarks.append(
            {
                "data_source": item.data_source,
                "dataset": item.dataset,
                "status": status,
                "latest": "static" if item.static else (latest.isoformat() if latest else None),
                "note": item.note,
            }
        )
    if not sources.get("stock_basic").is_empty() and scores["population_size"] == 0:
        issues.append({"severity": "error", "id": "empty_population", "message": "排雷样本为空。"})
    for gap in scores["data_gaps"]:
        if gap["status"] not in {"missing", "disabled"}:
            issues.append(
                {
                    "severity": "warning",
                    "id": "rule_data_gap",
                    "message": gap.get("note", "规则数据不足"),
                }
            )
    for gate in scores["missing_gates"]:
        status = gate.get("status")
        if status in {"not_supported", "registered_pending_backfill"}:
            issues.append(
                {
                    "severity": "warning",
                    "id": (
                        "rule_not_supported"
                        if status == "not_supported"
                        else "rule_pending_backfill"
                    ),
                    "message": f"{gate['rule_id']}: {gate.get('note', '本地数据尚未支持')}",
                }
            )
    status = (
        "failed"
        if any(item["severity"] == "error" for item in issues)
        else ("passed_with_warnings" if issues else "passed")
    )
    return {
        "schema_version": 1,
        "title": f"{config.title}质量报告",
        "status": status,
        "as_of_date": as_of_date.isoformat(),
        "summary": {
            "dataset_count": len(watermarks),
            "error_count": sum(item["severity"] == "error" for item in issues),
            "warning_count": sum(item["severity"] == "warning" for item in issues),
        },
        "watermarks": watermarks,
        "issues": issues,
        "data_gaps": scores["data_gaps"],
        "missing_gates": scores["missing_gates"],
    }


def latest_date(frame: pl.DataFrame, configured_column: str) -> date | None:
    """返回数据帧中指定日期列的最新日期。"""
    if frame.is_empty():
        return None
    column = (
        configured_column
        if configured_column and configured_column in frame.columns
        else next(
            (
                item
                for item in ("trade_date", "ann_date", "end_date", "suspend_date")
                if item in frame.columns
            ),
            "",
        )
    )
    if not column:
        return None
    values = [value for value in frame.get_column(column).to_list() if isinstance(value, date)]
    return max(values) if values else None


__all__ = ["build_manifest", "build_quality_report", "latest_date"]
