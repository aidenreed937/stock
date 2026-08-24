"""个股排雷运行产物写入。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.artifact_store import ArtifactRunPaths, ArtifactStore


@dataclass(frozen=True, slots=True)
class StockScreenRunPaths:
    """一次排雷运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    excluded: Path
    warned: Path
    passed: Path
    scored: Path
    scores: Path
    report_md: Path
    report_json: Path
    quality_report_md: Path
    quality_report_json: Path


@dataclass(frozen=True, slots=True)
class StockScreenArtifactPayload:
    """一次排雷运行需要写入的内容。"""

    manifest: dict[str, Any]
    excluded: pl.DataFrame
    warned: pl.DataFrame
    passed: pl.DataFrame
    scored: pl.DataFrame
    scores: dict[str, Any]
    report_markdown: str
    report_json: dict[str, Any]
    quality_report_markdown: str
    quality_report_json: dict[str, Any]


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
) -> StockScreenRunPaths:
    """按基准日与运行 ID 构造产物路径。"""
    generic = ArtifactStore.build_run_paths(as_of_date, artifact_root, run_id)
    return StockScreenRunPaths(
        root=generic.root,
        run_dir=generic.run_dir,
        latest_dir=generic.latest_dir,
        manifest=generic.run_dir / "manifest.json",
        excluded=generic.run_dir / "excluded.csv",
        warned=generic.run_dir / "warned.csv",
        passed=generic.run_dir / "passed.csv",
        scored=generic.run_dir / "scored.parquet",
        scores=generic.run_dir / "scores.json",
        report_md=generic.run_dir / "screen_report.md",
        report_json=generic.run_dir / "screen_report.json",
        quality_report_md=generic.run_dir / "quality_report.md",
        quality_report_json=generic.run_dir / "quality_report.json",
    )


def write_artifacts(
    paths: StockScreenRunPaths,
    payload: StockScreenArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入排雷清单、摘要和质量报告。"""
    generic = ArtifactRunPaths(paths.root, paths.run_dir, paths.latest_dir)
    with ArtifactStore(generic).transaction(update_latest=update_latest) as session:
        session.write_json("manifest.json", payload.manifest)
        session.write_csv("excluded.csv", _csv_frame(payload.excluded))
        session.write_csv("warned.csv", _csv_frame(payload.warned))
        session.write_csv("passed.csv", _csv_frame(payload.passed))
        if not payload.scored.is_empty():
            session.write_parquet("scored.parquet", payload.scored)
        session.write_json("scores.json", payload.scores)
        session.write_text("screen_report.md", payload.report_markdown)
        session.write_json("screen_report.json", payload.report_json)
        session.write_text("quality_report.md", payload.quality_report_markdown)
        session.write_json("quality_report.json", payload.quality_report_json)


def _csv_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """将输出契约中的列表列转换为 CSV 可写的文本列。"""
    expressions = []
    if "reasons" in frame.columns:
        expressions.append(pl.col("reasons").list.join("；").alias("reasons"))
    for column in ("rule_ids", "missing_rules"):
        if column in frame.columns:
            expressions.append(pl.col(column).list.join(",").alias(column))
    return frame.with_columns(expressions) if expressions else frame


__all__ = [
    "StockScreenArtifactPayload",
    "StockScreenRunPaths",
    "build_run_paths",
    "write_artifacts",
]
