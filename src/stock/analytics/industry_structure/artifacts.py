"""行业结构分析运行产物写入。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl

MappingLike = dict[str, Any]


@dataclass(frozen=True, slots=True)
class IndustryStructureRunPaths:
    """一次行业结构分析运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    facts: Path
    industry_panel: Path
    scores: Path
    report_md: Path
    report_json: Path
    human_report_md: Path
    quality_report_md: Path
    quality_report_json: Path


@dataclass(frozen=True, slots=True)
class IndustryStructureArtifactPayload:
    """一次运行需要写入的产物内容。"""

    manifest: MappingLike
    facts: pl.DataFrame
    industry_panel: pl.DataFrame
    scores: MappingLike
    report_markdown: str
    report_json: MappingLike
    human_report_markdown: str
    quality_report_markdown: str
    quality_report_json: MappingLike


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
) -> IndustryStructureRunPaths:
    """按 as_of 日期与 run_id 构造产物路径。"""
    root = Path(artifact_root)
    actual_run_id = run_id or f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run_dir = root / "runs" / f"as_of={as_of_date.isoformat()}" / actual_run_id
    latest_dir = root / "latest"
    return IndustryStructureRunPaths(
        root=root,
        run_dir=run_dir,
        latest_dir=latest_dir,
        manifest=run_dir / "manifest.json",
        facts=run_dir / "facts.parquet",
        industry_panel=run_dir / "industry_panel.parquet",
        scores=run_dir / "scores.json",
        report_md=run_dir / "report.md",
        report_json=run_dir / "report.json",
        human_report_md=run_dir / "human_report.md",
        quality_report_md=run_dir / "quality_report.md",
        quality_report_json=run_dir / "quality_report.json",
    )


def write_artifacts(
    paths: IndustryStructureRunPaths,
    payload: IndustryStructureArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入一次运行的 manifest、facts、scores 和报告产物。"""
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(paths.manifest, payload.manifest)
    payload.facts.write_parquet(paths.facts)
    payload.industry_panel.write_parquet(paths.industry_panel)
    _write_json(paths.scores, payload.scores)
    paths.report_md.write_text(payload.report_markdown, encoding="utf-8")
    _write_json(paths.report_json, payload.report_json)
    paths.human_report_md.write_text(payload.human_report_markdown, encoding="utf-8")
    paths.quality_report_md.write_text(payload.quality_report_markdown, encoding="utf-8")
    _write_json(paths.quality_report_json, payload.quality_report_json)

    if update_latest:
        _copy_to_latest(paths)


def _copy_to_latest(paths: IndustryStructureRunPaths) -> None:
    paths.latest_dir.mkdir(parents=True, exist_ok=True)
    for source in (
        paths.manifest,
        paths.facts,
        paths.industry_panel,
        paths.scores,
        paths.report_md,
        paths.report_json,
        paths.human_report_md,
        paths.quality_report_md,
        paths.quality_report_json,
    ):
        shutil.copy2(source, paths.latest_dir / source.name)


def _write_json(path: Path, payload: MappingLike) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _json_default(value: object) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)
