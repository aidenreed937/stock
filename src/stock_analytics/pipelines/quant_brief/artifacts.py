"""量化投研简报产物写入。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

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
) -> QuantBriefRunPaths:
    """按基准日与 run_id 构造产物路径。"""
    root = Path(artifact_root)
    actual_run_id = run_id or f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run_dir = root / "runs" / f"as_of={as_of_date.isoformat()}" / actual_run_id
    latest_dir = root / "latest"
    return QuantBriefRunPaths(
        root=root,
        run_dir=run_dir,
        latest_dir=latest_dir,
        manifest=run_dir / "manifest.json",
        brief_md=run_dir / "brief_report.md",
        brief_json=run_dir / "brief_report.json",
    )


def write_artifacts(
    paths: QuantBriefRunPaths,
    payload: QuantBriefArtifactPayload,
    *,
    update_latest: bool = True,
) -> None:
    """写入一次运行的 manifest 和简报产物。"""
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(paths.manifest, payload.manifest)
    paths.brief_md.write_text(payload.brief_markdown, encoding="utf-8")
    _write_json(paths.brief_json, payload.brief_json)
    if update_latest:
        _copy_to_latest(paths)


def _copy_to_latest(paths: QuantBriefRunPaths) -> None:
    paths.latest_dir.mkdir(parents=True, exist_ok=True)
    for source in (paths.manifest, paths.brief_md, paths.brief_json):
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


__all__ = [
    "QuantBriefArtifactPayload",
    "QuantBriefRunPaths",
    "build_run_paths",
    "write_artifacts",
]
