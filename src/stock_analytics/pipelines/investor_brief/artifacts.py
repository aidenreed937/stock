"""投资者简报产物写入。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.artifact_contracts import RunClass
from stock_analytics.pipelines.artifact_store import ArtifactRunPaths, ArtifactStore

MappingLike = dict[str, Any]


@dataclass(frozen=True, slots=True)
class InvestorBriefRunPaths:
    """一次投资者简报运行的文件路径集合。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    manifest: Path
    brief_md: Path
    brief_json: Path
    run_class: RunClass = "official"


@dataclass(frozen=True, slots=True)
class InvestorBriefArtifactPayload:
    """一次运行需要写入的产物内容。"""

    manifest: MappingLike
    brief_markdown: str
    brief_json: MappingLike


def build_run_paths(
    as_of_date: date,
    artifact_root: Path | str,
    run_id: str | None = None,
    *,
    run_class: RunClass = "official",
) -> InvestorBriefRunPaths:
    """按 as_of 日期与 run_id 构造产物路径。"""
    generic = ArtifactStore.build_run_paths(
        as_of_date,
        artifact_root,
        run_id,
        run_class=run_class,
    )
    return InvestorBriefRunPaths(
        root=generic.root,
        run_dir=generic.run_dir,
        latest_dir=generic.latest_dir,
        run_class=generic.run_class,
        manifest=generic.run_dir / "manifest.json",
        brief_md=generic.run_dir / "brief_report.md",
        brief_json=generic.run_dir / "brief_report.json",
    )


def write_artifacts(
    paths: InvestorBriefRunPaths,
    payload: InvestorBriefArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入一次运行的 manifest 和简报产物。"""
    generic = ArtifactRunPaths(
        paths.root,
        paths.run_dir,
        paths.latest_dir,
        artifact_type="investor_brief",
        run_class=paths.run_class,
    )
    with ArtifactStore(generic).transaction(update_latest=update_latest) as session:
        session.write_json("manifest.json", payload.manifest)
        session.write_text("brief_report.md", payload.brief_markdown)
        session.write_json("brief_report.json", payload.brief_json)
