"""量化投研简报产物写入。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.artifact_store import ArtifactRunPaths, ArtifactStore

MappingLike = dict[str, Any]


@dataclass(frozen=True, slots=True)
class QuantBriefRunPaths:
    """一次量化投研简报运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    brief_md: Path
    brief_json: Path


@dataclass(frozen=True, slots=True)
class QuantBriefArtifactPayload:
    """一次运行需要写入的产物内容。"""

    manifest: MappingLike
    brief_markdown: str
    brief_json: MappingLike


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
    *,
    latest_root: Path | str | None = None,
) -> QuantBriefRunPaths:
    """按基准日与 run_id 构造运行和共享 latest 产物路径。"""
    generic = ArtifactStore.build_run_paths(
        as_of_date,
        artifact_root,
        run_id,
        latest_root=latest_root,
    )
    return QuantBriefRunPaths(
        root=generic.root,
        run_dir=generic.run_dir,
        latest_dir=generic.latest_dir,
        manifest=generic.run_dir / "manifest.json",
        brief_md=generic.run_dir / "brief_report.md",
        brief_json=generic.run_dir / "brief_report.json",
    )


def write_artifacts(
    paths: QuantBriefRunPaths,
    payload: QuantBriefArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入一次运行的 manifest 和简报产物。"""
    generic = ArtifactRunPaths(paths.root, paths.run_dir, paths.latest_dir)
    with ArtifactStore(generic).transaction(update_latest=update_latest) as session:
        session.write_json("manifest.json", payload.manifest)
        session.write_text("brief_report.md", payload.brief_markdown)
        session.write_json("brief_report.json", payload.brief_json)


__all__ = [
    "QuantBriefArtifactPayload",
    "QuantBriefRunPaths",
    "build_run_paths",
    "write_artifacts",
]
