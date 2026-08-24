"""业务管线运行产物索引。"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkstemp
from typing import Any

INDEX_FILENAME = "run_index.json"
INDEX_SCHEMA_VERSION = 1


def rebuild_run_index(root: Path | str) -> dict[str, Any]:
    """扫描运行目录并原子重建运行索引。"""
    root_path = Path(root)
    if not root_path.is_dir():
        raise NotADirectoryError(f"产物根目录不是目录: {root_path}")
    runs_root = root_path / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    lock_path = runs_root / ".run_index.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = []
        for date_dir in sorted(runs_root.glob("as_of=*")):
            if not date_dir.is_dir():
                continue
            for run_dir in sorted(date_dir.glob("run_*")):
                if not run_dir.is_dir() or run_dir.is_symlink():
                    continue
                manifest = _read_manifest(run_dir / "manifest.json")
                if manifest is None:
                    continue
                entries.append(_build_entry(root_path, run_dir, manifest))
        entries.sort(key=lambda item: (str(item["as_of_date"]), str(item["run_id"])))
        payload: dict[str, Any] = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "artifact_root": str(root_path),
            "runs": entries,
        }
        _atomic_write(root_path / INDEX_FILENAME, payload)
        fcntl.flock(lock, fcntl.LOCK_UN)
    return payload


def read_run_index(root: Path | str) -> dict[str, Any] | None:
    """读取已有运行索引，不存在或格式错误时返回 None。"""
    return _read_manifest(Path(root) / INDEX_FILENAME)


def _build_entry(root: Path, run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_type": manifest.get("artifact_type"),
        "run_class": manifest.get("run_class", "official"),
        "run_id": manifest.get("run_id", run_dir.name),
        "as_of_date": manifest.get("as_of_date", run_dir.parent.name.removeprefix("as_of=")),
        "generated_at": manifest.get("generated_at"),
        "run_status": manifest.get("run_status"),
        "run_dir": run_dir.relative_to(root).as_posix(),
        "artifact_files": manifest.get("artifact_files", []),
    }


def _read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["INDEX_FILENAME", "INDEX_SCHEMA_VERSION", "read_run_index", "rebuild_run_index"]
