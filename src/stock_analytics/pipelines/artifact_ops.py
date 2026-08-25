"""业务管线运行产物运维 Facade。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import time

from stock_analytics.pipelines.artifact_cleanup import (
    ArtifactRunCandidate,
    collect_run_candidates,
    delete_run_candidates,
)
from stock_analytics.pipelines.artifact_contracts import RUN_CLASSES, RunClass
from stock_analytics.pipelines.artifact_index import rebuild_run_index


@dataclass(frozen=True)
class ArtifactIndexResult:
    """运行索引重建结果。"""

    root: Path
    run_count: int


@dataclass(frozen=True)
class ArtifactCleanupResult:
    """产物清理预览或执行结果。"""

    root: Path
    candidates: list[ArtifactRunCandidate]
    applied: bool
    deleted: int = 0
    skipped: int = 0


def index_artifacts(root: Path | str) -> ArtifactIndexResult:
    """重建管线运行索引。"""
    resolved_root = Path(root)
    payload = rebuild_run_index(resolved_root)
    return ArtifactIndexResult(resolved_root, len(payload["runs"]))


def cleanup_artifacts(
    root: Path | str,
    older_than_days: float,
    *,
    run_class: RunClass,
    latest_root: Path | str | None = None,
    keep_latest: bool = True,
    apply: bool = False,
) -> ArtifactCleanupResult:
    """预览或执行历史运行包清理。"""
    resolved_root = Path(root)
    candidates = collect_run_candidates(
        resolved_root,
        older_than_days,
        run_class=run_class,
        latest_root=latest_root,
        keep_latest=keep_latest,
    )
    if not apply:
        return ArtifactCleanupResult(resolved_root, candidates, False)
    cutoff = time() - older_than_days * 24 * 60 * 60
    deleted, skipped = delete_run_candidates(candidates, root=resolved_root, cutoff=cutoff)
    rebuild_run_index(resolved_root)
    return ArtifactCleanupResult(resolved_root, candidates, True, deleted, skipped)


__all__ = [
    "RUN_CLASSES",
    "ArtifactCleanupResult",
    "ArtifactIndexResult",
    "ArtifactRunCandidate",
    "cleanup_artifacts",
    "index_artifacts",
]
