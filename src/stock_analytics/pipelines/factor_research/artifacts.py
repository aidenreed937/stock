"""因子准入评估产物写入。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.artifacts import ArtifactRunPaths, ArtifactStore, RunClass

MappingLike = dict[str, Any]


@dataclass(frozen=True, slots=True)
class FactorResearchRunPaths:
    """一次因子准入评估运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    report_md: Path
    report_json: Path
    run_class: RunClass = "official"


@dataclass(frozen=True, slots=True)
class FactorResearchArtifactPayload:
    """一次运行需要写入的产物内容。"""

    manifest: MappingLike
    report_markdown: str
    report_json: MappingLike


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
    *,
    latest_root: Path | str | None = None,
    run_class: RunClass = "official",
) -> FactorResearchRunPaths:
    """按基准日与 run_id 构造运行和共享 latest 产物路径。"""
    generic = ArtifactStore.build_run_paths(
        as_of_date,
        artifact_root,
        run_id,
        latest_root=latest_root,
        run_class=run_class,
    )
    return FactorResearchRunPaths(
        root=generic.root,
        run_dir=generic.run_dir,
        latest_dir=generic.latest_dir,
        run_class=generic.run_class,
        manifest=generic.run_dir / "manifest.json",
        report_md=generic.run_dir / "factor_research.md",
        report_json=generic.run_dir / "factor_research.json",
    )


def write_artifacts(
    paths: FactorResearchRunPaths,
    payload: FactorResearchArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入一次运行的 manifest 和因子评估报告产物。"""
    generic = ArtifactRunPaths(
        paths.root,
        paths.run_dir,
        paths.latest_dir,
        artifact_type="factor_research",
        run_class=paths.run_class,
    )
    with ArtifactStore(generic).transaction(update_latest=update_latest) as session:
        session.write_json("manifest.json", payload.manifest)
        session.write_text("factor_research.md", payload.report_markdown)
        session.write_json("factor_research.json", payload.report_json)


__all__ = [
    "FactorResearchArtifactPayload",
    "FactorResearchRunPaths",
    "build_run_paths",
    "write_artifacts",
]
