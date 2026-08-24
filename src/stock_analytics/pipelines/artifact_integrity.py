"""运行产物文件完整性计算与校验。"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.artifact_validator_files import ArtifactValidationIssue

CHUNK_SIZE = 1024 * 1024


def build_artifact_integrity(root: Path, names: list[str]) -> dict[str, dict[str, int | str]]:
    """为非 Manifest 文件生成字节数和 SHA256。"""
    result: dict[str, dict[str, int | str]] = {}
    for name in sorted(set(names)):
        if name == "manifest.json":
            continue
        path = root / name
        result[name] = {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    return result


def check_artifact_integrity(
    root: Path,
    actual_files: set[str],
    declared_files: list[str] | None,
    manifest: Mapping[str, Any],
    issues: list[ArtifactValidationIssue],
    *,
    required: bool = False,
) -> None:
    """校验 Manifest 中已记录的文件字节数和 SHA256。"""
    raw_integrity = manifest.get("artifact_integrity")
    if raw_integrity is None:
        if required:
            issues.append(
                ArtifactValidationIssue(
                    "artifact_integrity_missing",
                    "Manifest 缺少字段: artifact_integrity",
                    "artifact_integrity",
                )
            )
        return
    if not isinstance(raw_integrity, Mapping):
        issues.append(
            ArtifactValidationIssue(
                "artifact_integrity_invalid",
                "Manifest 字段 artifact_integrity 必须是文件映射",
                "artifact_integrity",
            )
        )
        return

    expected_files = set(declared_files or ()) - {"manifest.json"}
    actual_integrity = {str(name) for name in raw_integrity}
    for name in sorted(expected_files - actual_integrity):
        issues.append(
            ArtifactValidationIssue(
                "artifact_integrity_missing",
                f"Manifest 缺少文件完整性记录: {name}",
                name,
            )
        )
    for name in sorted(actual_integrity - expected_files):
        issues.append(
            ArtifactValidationIssue(
                "artifact_integrity_unlisted",
                f"Manifest 存在未声明文件的完整性记录: {name}",
                name,
            )
        )

    for name in sorted(expected_files & actual_integrity & actual_files):
        item = raw_integrity.get(name)
        if not isinstance(item, Mapping):
            issues.append(
                ArtifactValidationIssue(
                    "artifact_integrity_invalid",
                    f"文件完整性记录必须是映射: {name}",
                    name,
                )
            )
            continue
        expected_bytes = item.get("bytes")
        expected_sha256 = item.get("sha256")
        if not isinstance(expected_bytes, int) or not isinstance(expected_sha256, str):
            issues.append(
                ArtifactValidationIssue(
                    "artifact_integrity_invalid",
                    f"文件完整性记录缺少有效 bytes/sha256: {name}",
                    name,
                )
            )
            continue
        path = root / name
        actual_bytes = path.stat().st_size
        actual_sha256 = _sha256(path)
        if expected_bytes != actual_bytes or expected_sha256 != actual_sha256:
            issues.append(
                ArtifactValidationIssue(
                    "artifact_integrity_mismatch",
                    f"文件完整性不一致: {name}",
                    name,
                )
            )


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["build_artifact_integrity", "check_artifact_integrity"]
