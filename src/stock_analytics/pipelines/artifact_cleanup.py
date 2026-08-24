"""业务管线历史运行产物的安全清理。"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from stock_analytics.pipelines.artifact_contracts import RunClass, normalize_run_class

SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class ArtifactRunCandidate:
    """一项可清理的历史运行包。"""

    path: Path
    run_id: str
    as_of_date: str
    run_class: RunClass
    size_bytes: int
    mtime: float


def collect_run_candidates(
    root: Path | str,
    older_than_days: float = 30.0,
    *,
    run_class: RunClass | None = None,
    latest_root: Path | str | None = None,
    keep_latest: bool = True,
    now: float | None = None,
) -> list[ArtifactRunCandidate]:
    """收集超过保留期且不影响 latest 的运行包。"""
    root_path = _resolve_root(root)
    if older_than_days < 0:
        raise ValueError("older_than_days 不能小于 0")
    selected_class = normalize_run_class(run_class) if run_class is not None else None
    cutoff = (time.time() if now is None else now) - older_than_days * SECONDS_PER_DAY
    latest_identity = _latest_identity(latest_root or root_path) if keep_latest else None
    candidates: list[ArtifactRunCandidate] = []
    runs_root = root_path / "runs"
    for date_dir in sorted(runs_root.glob("as_of=*")) if runs_root.is_dir() else []:
        if not date_dir.is_dir() or date_dir.is_symlink():
            continue
        as_of_date = date_dir.name.removeprefix("as_of=")
        for run_dir in sorted(date_dir.glob("run_*")):
            if not run_dir.is_dir() or run_dir.is_symlink():
                continue
            try:
                stat_result = run_dir.stat()
            except OSError:
                continue
            if stat_result.st_mtime > cutoff:
                continue
            manifest = _read_manifest(run_dir / "manifest.json")
            if manifest is None:
                continue
            current_class = normalize_run_class(str(manifest.get("run_class", "official")))
            run_id = str(manifest.get("run_id", run_dir.name))
            if selected_class is not None and current_class != selected_class:
                continue
            if latest_identity == (as_of_date, run_id):
                continue
            candidates.append(
                ArtifactRunCandidate(
                    path=run_dir,
                    run_id=run_id,
                    as_of_date=as_of_date,
                    run_class=current_class,
                    size_bytes=_directory_size(run_dir),
                    mtime=stat_result.st_mtime,
                )
            )
    return candidates


def delete_run_candidates(
    candidates: list[ArtifactRunCandidate],
    *,
    root: Path | str,
    cutoff: float,
) -> tuple[int, int]:
    """删除候选运行包，并对扫描后的新目录跳过处理。"""
    root_path = _resolve_root(root)
    deleted = 0
    skipped = 0
    for candidate in candidates:
        path = candidate.path
        runs_root = root_path / "runs"
        if (
            path.is_symlink()
            or not path.is_relative_to(runs_root)
            or path.name != candidate.run_id
            or not path.parent.name.startswith("as_of=")
        ):
            raise ValueError(f"候选路径不是受控运行目录: {path}")
        try:
            if path.stat().st_mtime > cutoff:
                skipped += 1
                continue
            shutil.rmtree(path)
        except FileNotFoundError:
            skipped += 1
            continue
        deleted += 1
    return deleted, skipped


def _latest_identity(root: Path | str) -> tuple[str, str] | None:
    latest_dir = _resolve_root(root) / "latest"
    if not latest_dir.exists():
        return None
    manifest = _read_manifest(latest_dir / "manifest.json")
    if manifest is None:
        raise ValueError(f"latest Manifest 无法读取，停止清理: {latest_dir}")
    as_of_date = manifest.get("as_of_date")
    run_id = manifest.get("run_id")
    if not isinstance(as_of_date, str) or not isinstance(run_id, str):
        raise ValueError(f"latest Manifest 缺少 as_of_date/run_id，停止清理: {latest_dir}")
    return as_of_date, run_id


def _resolve_root(root: Path | str) -> Path:
    resolved = Path(root).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"产物根目录不存在: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"产物根路径不是目录: {resolved}")
    return resolved


def _read_manifest(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_symlink() or not child.is_file():
            continue
        try:
            total += child.stat().st_size
        except OSError:
            continue
    return total


__all__ = ["ArtifactRunCandidate", "collect_run_candidates", "delete_run_candidates"]
