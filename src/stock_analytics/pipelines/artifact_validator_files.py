"""Manifest 文件清单与目录文件集合校验辅助。"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True, slots=True)
class ArtifactValidationIssue:
    """一条产物校验问题。"""

    code: str
    message: str
    filename: str | None = None


def actual_files(root: Path) -> list[str]:
    """返回目录内所有文件的相对 POSIX 路径。"""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def load_manifest(
    path: Path,
    issues: list[ArtifactValidationIssue],
) -> dict[str, Any] | None:
    """读取 Manifest JSON，并将格式问题追加到校验结果。"""
    if not path.is_file():
        issues.append(
            ArtifactValidationIssue(
                "required_file_missing",
                "缺少必需文件: manifest.json",
                "manifest.json",
            )
        )
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        issues.append(
            ArtifactValidationIssue(
                "manifest_invalid",
                f"Manifest 无法读取或不是有效 JSON: {error}",
                "manifest.json",
            )
        )
        return None
    if not isinstance(payload, dict):
        issues.append(
            ArtifactValidationIssue(
                "manifest_invalid",
                "Manifest 必须是 JSON 对象",
                "manifest.json",
            )
        )
        return None
    return payload


def manifest_names(
    manifest: Mapping[str, Any],
    field: str,
    issues: list[ArtifactValidationIssue],
    *,
    required: bool,
) -> list[str] | None:
    """读取 Manifest 中的文件名列表或文件映射值。"""
    if field not in manifest:
        if required:
            issues.append(
                ArtifactValidationIssue(
                    "manifest_field_missing",
                    f"Manifest 缺少字段: {field}",
                    field,
                )
            )
        return None

    value = manifest[field]
    raw_names: list[Any]
    if field == "artifact_files":
        if not isinstance(value, list):
            issues.append(
                ArtifactValidationIssue(
                    "manifest_field_invalid",
                    f"Manifest 字段 {field} 必须是文件名列表",
                    field,
                )
            )
            return None
        raw_names = value
    else:
        if not isinstance(value, Mapping):
            issues.append(
                ArtifactValidationIssue(
                    "manifest_field_invalid",
                    f"Manifest 字段 {field} 必须是文件映射",
                    field,
                )
            )
            return None
        raw_names = list(value.values())

    names: list[str] = []
    for raw_name in raw_names:
        if not isinstance(raw_name, str) or not _is_safe_relative_name(raw_name):
            issues.append(
                ArtifactValidationIssue(
                    "manifest_file_name_invalid",
                    f"Manifest 字段 {field} 包含非法相对文件名: {raw_name!r}",
                    field,
                )
            )
            continue
        names.append(raw_name)

    for name, count in Counter(names).items():
        if count > 1:
            issues.append(
                ArtifactValidationIssue(
                    "manifest_file_name_duplicate",
                    f"Manifest 字段 {field} 包含重复文件名: {name}",
                    name,
                )
            )
    return names


def check_artifact_files(
    actual: set[str],
    declared: list[str],
    issues: list[ArtifactValidationIssue],
) -> None:
    """校验 Manifest 实际写入清单与目录集合一致。"""
    declared_set = set(declared)
    for name in sorted(declared_set - actual):
        issues.append(
            ArtifactValidationIssue(
                "artifact_file_missing",
                f"Manifest 声明了文件，但目录中不存在: {name}",
                name,
            )
        )
    for name in sorted(actual - declared_set):
        issues.append(
            ArtifactValidationIssue(
                "artifact_file_unlisted",
                f"目录中存在未被 Manifest 声明的文件: {name}",
                name,
            )
        )


def check_required_files(
    actual: set[str],
    required: list[str],
    issues: list[ArtifactValidationIssue],
) -> None:
    """校验 Manifest 必需文件是否存在。"""
    for name in sorted(set(required) - actual):
        issues.append(
            ArtifactValidationIssue(
                "required_file_missing",
                f"缺少必需文件: {name}",
                name,
            )
        )


def check_optional_files(
    actual: set[str],
    declared: set[str],
    optional: list[str],
    issues: list[ArtifactValidationIssue],
) -> None:
    """校验可选文件的存在状态是否与实际写入清单一致。"""
    for name in sorted(set(optional)):
        present = name in actual
        listed = name in declared
        if present == listed:
            continue
        state = "存在但未列入 artifact_files" if present else "已列入 artifact_files 但实际不存在"
        issues.append(
            ArtifactValidationIssue(
                "optional_file_state_invalid",
                f"可选文件状态不一致: {name}（{state}）",
                name,
            )
        )


def _is_safe_relative_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and name != "." and not path.is_absolute() and ".." not in path.parts


__all__ = [
    "ArtifactValidationIssue",
    "actual_files",
    "check_artifact_files",
    "check_optional_files",
    "check_required_files",
    "load_manifest",
    "manifest_names",
]
