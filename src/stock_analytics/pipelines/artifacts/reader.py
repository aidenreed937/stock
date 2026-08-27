"""分析产物运行目录定位与 Manifest 校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.artifacts.contracts import normalize_run_class
from stock_analytics.pipelines.artifacts.validator import ArtifactValidator


class ArtifactUnavailableError(RuntimeError):
    """产物缺失、过期或完整性校验失败。"""


@dataclass(frozen=True, slots=True)
class ArtifactRun:
    """通过校验的一次分析产物运行。"""

    root: Path
    run_dir: Path
    manifest: dict[str, Any]

    def path(self, filename: str) -> Path:
        """返回运行目录内的文件路径。"""
        return self.run_dir / filename

    def read_json(self, filename: str) -> dict[str, Any]:
        """读取运行目录内的 JSON 对象。"""
        path = self.path(filename)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactUnavailableError(f"无法读取产物 JSON: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ArtifactUnavailableError(f"产物 JSON 必须是对象: {path}")
        return payload


def resolve_artifact_run(
    root: Path | str,
    *,
    as_of_date: date | str | None = "latest",
    expected_artifact_type: str,
    expected_run_class: str | None = None,
    run_id: str | None = None,
) -> ArtifactRun:
    """定位并校验指定基准日的最新一次产物运行。"""
    artifact_root = Path(root)
    date_text = (
        as_of_date.isoformat() if isinstance(as_of_date, date) else str(as_of_date or "latest")
    )
    run_dir = select_artifact_run_dir(
        artifact_root,
        as_of_date=date_text,
        expected_run_class=expected_run_class,
        run_id=run_id,
    )
    if run_dir is None and date_text == "latest":
        run_dir = artifact_root / "latest"
    if run_dir is None:
        if run_id is not None:
            raise ArtifactUnavailableError(
                f"缺少 {expected_artifact_type} 指定运行: as_of={date_text}, run_id={run_id}"
            )
        date_root = artifact_root / "runs" / f"as_of={date_text}"
        raise ArtifactUnavailableError(f"缺少 {expected_artifact_type} 产物运行: {date_root}")

    result = ArtifactValidator().validate(
        run_dir,
        expected_artifact_type=expected_artifact_type,
        expected_run_class=expected_run_class,
    )
    if not result.valid or result.manifest is None:
        details = "；".join(issue.message for issue in result.issues[:3])
        raise ArtifactUnavailableError(
            f"{expected_artifact_type} 产物不可用: {run_dir}" + (f"；{details}" if details else "")
        )
    if date_text != "latest" and result.manifest.get("as_of_date") != date_text:
        raise ArtifactUnavailableError(
            f"{expected_artifact_type} 产物基准日不匹配: "
            f"期望 {date_text}，实际 {result.manifest.get('as_of_date')}"
        )
    return ArtifactRun(artifact_root, run_dir, result.manifest)


def select_artifact_run_dir(
    root: Path | str,
    *,
    as_of_date: date | str | None = "latest",
    expected_run_class: str | None = None,
    run_id: str | None = None,
) -> Path | None:
    """按基准日和运行类别选择最新运行目录，不执行文件完整性校验。"""
    artifact_root = Path(root)
    date_text = (
        as_of_date.isoformat() if isinstance(as_of_date, date) else str(as_of_date or "latest")
    )
    if expected_run_class is not None:
        normalize_run_class(expected_run_class)
    if run_id is not None:
        _validate_run_id(run_id)
    if date_text == "latest":
        if run_id is not None:
            latest_manifest = artifact_root / "latest" / "manifest.json"
            if not latest_manifest.is_file():
                return None
            try:
                manifest = json.loads(latest_manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if not isinstance(manifest, dict):
                return None
            resolved_date = manifest.get("as_of_date")
            if not isinstance(resolved_date, str) or not resolved_date:
                return None
            candidate = artifact_root / "runs" / f"as_of={resolved_date}" / run_id
            return candidate if candidate.is_dir() else None
        run_dir = artifact_root / "latest"
        return run_dir if run_dir.is_dir() else None

    date_root = artifact_root / "runs" / f"as_of={date_text}"
    if run_id is not None:
        candidate = date_root / run_id
        return candidate if candidate.is_dir() else None
    candidates = sorted(path for path in date_root.glob("run_*") if path.is_dir())
    if expected_run_class is None:
        return candidates[-1] if candidates else None
    for candidate in reversed(candidates):
        manifest_path = candidate / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(manifest, dict)
            and manifest.get("run_class", "official") == expected_run_class
        ):
            return candidate
    return None


def _validate_run_id(run_id: str) -> None:
    path = Path(run_id)
    if not run_id or path.is_absolute() or path.name != run_id or ".." in path.parts:
        raise ValueError(f"run_id 必须是单段相对目录名: {run_id!r}")


__all__ = [
    "ArtifactRun",
    "ArtifactUnavailableError",
    "resolve_artifact_run",
    "select_artifact_run_dir",
]
