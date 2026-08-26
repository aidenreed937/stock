"""分析产物运行目录定位与 Manifest 校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.artifact_validator import ArtifactValidator


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
) -> ArtifactRun:
    """定位并校验指定基准日的最新一次产物运行。"""
    artifact_root = Path(root)
    date_text = (
        as_of_date.isoformat() if isinstance(as_of_date, date) else str(as_of_date or "latest")
    )
    if date_text == "latest":
        run_dir = artifact_root / "latest"
    else:
        date_root = artifact_root / "runs" / f"as_of={date_text}"
        candidates = sorted(path for path in date_root.glob("run_*") if path.is_dir())
        if not candidates:
            raise ArtifactUnavailableError(f"缺少 {expected_artifact_type} 产物运行: {date_root}")
        run_dir = candidates[-1]

    result = ArtifactValidator().validate(
        run_dir,
        expected_artifact_type=expected_artifact_type,
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


__all__ = ["ArtifactRun", "ArtifactUnavailableError", "resolve_artifact_run"]
