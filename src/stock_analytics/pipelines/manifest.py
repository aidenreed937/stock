"""业务管线 Manifest 公共字段与数据水位辅助。"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable, Mapping
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_VERSION = 1
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def build_manifest_base(
    *,
    artifact_type: str,
    schema_version: int,
    title: str,
    run_id: str,
    as_of_date: date,
    artifact_root: Path | str,
    config_path: Path | str | None,
    inputs: Mapping[str, Any] | None = None,
    parents: Mapping[str, Any] | None = None,
    watermarks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造所有管线共享的 Manifest 基础字段。"""
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "schema_version": schema_version,
        "title": title,
        "run_id": run_id,
        "generated_at": _generated_at(),
        "as_of_date": as_of_date.isoformat(),
        "run_status": "succeeded",
        "artifact_root": str(artifact_root),
        "provenance": _build_provenance(config_path),
        "inputs": dict(inputs or {}),
        "parents": dict(parents or {}),
        "watermarks": dict(watermarks or {}),
    }


def build_watermark_index(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """将事实表中的数据水位行整理为稳定的 Manifest 索引。"""
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("category", "")) != "data_watermark":
            continue
        data_source = str(row.get("data_source", ""))
        dataset = str(row.get("dataset", ""))
        if not data_source or not dataset:
            continue
        latest = row.get("value_text")
        result[f"{data_source}.{dataset}"] = {
            "data_source": data_source,
            "dataset": dataset,
            "status": row.get("status"),
            "latest": latest if latest not in (None, "") else None,
            "sample_size": row.get("sample_size"),
            "source": row.get("source"),
            "note": row.get("note", ""),
        }
    return result


def _build_provenance(config_path: Path | str | None) -> dict[str, Any]:
    dirty = _run_git("status", "--porcelain", "--untracked-files=all")
    return {
        "git_commit": _run_git("rev-parse", "HEAD"),
        "git_dirty": None if dirty is None else bool(dirty),
        "config_sha256": _file_sha256(Path(config_path)) if config_path is not None else None,
    }


def _generated_at() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _file_sha256(path: Path) -> str | None:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _run_git(*args: str) -> str | None:
    git = shutil.which("git")
    if git is not None:
        try:
            import os

            env = {
                **os.environ,
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null",
            }
            result = subprocess.run(  # noqa: S603
                [git, *args],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
                env=env,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    if "rev-parse" in args and "HEAD" in args:
        return _read_git_head_fallback()
    return None


def _read_git_head_fallback() -> str | None:
    """直接从 .git/ 目录结构读取当前 HEAD commit SHA，供沙箱无 git 或全局 gitconfig 隔离时兜底。"""
    try:
        git_dir = _PROJECT_ROOT / ".git"
        if not git_dir.exists():
            return None
        head_path = git_dir / "HEAD"
        if not head_path.exists():
            return None
        head_content = head_path.read_text(encoding="utf-8").strip()
        if not head_content.startswith("ref: "):
            return head_content if len(head_content) == 40 else None
        ref_rel = head_content[5:].strip()
        ref_path = git_dir / ref_rel
        if ref_path.exists():
            return ref_path.read_text(encoding="utf-8").strip()
        packed_refs = git_dir / "packed-refs"
        if packed_refs.exists():
            for line in packed_refs.read_text(encoding="utf-8").splitlines():
                parts = line.strip().split()
                if len(parts) == 2 and parts[1] == ref_rel:
                    return parts[0]
    except OSError:
        return None
    return None


__all__ = ["MANIFEST_SCHEMA_VERSION", "build_manifest_base", "build_watermark_index"]
