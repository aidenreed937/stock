"""业务管线运行产物的 Manifest 与文件清单校验。"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ArtifactValidationIssue:
    """一条产物校验问题。"""

    code: str
    message: str
    filename: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactValidationResult:
    """一次产物校验结果。"""

    artifact_dir: Path
    manifest: dict[str, Any] | None
    issues: tuple[ArtifactValidationIssue, ...]

    @property
    def status(self) -> Literal["passed", "failed"]:
        """返回机器可读的校验状态。"""
        return "passed" if not self.issues else "failed"

    @property
    def valid(self) -> bool:
        """返回产物是否通过校验。"""
        return not self.issues


class ArtifactValidator:
    """校验运行目录中的 Manifest、必需文件与可选文件状态。"""

    def validate(self, artifact_dir: Path | str) -> ArtifactValidationResult:
        """校验一个已发布的运行目录。"""
        root = Path(artifact_dir)
        if root.name == "latest":
            return self.validate_latest(root)
        return self._validate_directory(root, check_path=True)

    def validate_latest(self, latest_dir: Path | str) -> ArtifactValidationResult:
        """校验 latest 目录，并确认其对应的运行目录完整。"""
        root = Path(latest_dir)
        result = self._validate_directory(root, check_path=False)
        issues = list(result.issues)
        if result.manifest is not None:
            source_dir = _resolve_latest_source(result.manifest, issues)
            if source_dir is not None:
                source_result = self._validate_directory(source_dir, check_path=True)
                if not source_result.valid:
                    issues.append(
                        ArtifactValidationIssue(
                            "latest_source_invalid",
                            f"latest 对应的运行目录未通过校验: {source_dir}",
                        )
                    )
                elif source_result.manifest is not None:
                    _check_latest_match(
                        root, source_dir, result.manifest, source_result.manifest, issues
                    )
        return ArtifactValidationResult(root, result.manifest, tuple(issues))

    def _validate_directory(
        self,
        root: Path,
        *,
        check_path: bool,
    ) -> ArtifactValidationResult:
        """校验一个目录本身的文件与 Manifest。"""
        issues: list[ArtifactValidationIssue] = []
        if not root.is_dir():
            issues.append(
                ArtifactValidationIssue(
                    "artifact_dir_missing",
                    f"产物目录不存在: {root}",
                )
            )
            return ArtifactValidationResult(root, None, tuple(issues))

        actual_files = _actual_files(root)
        manifest = _load_manifest(root / "manifest.json", issues)
        if manifest is None:
            return ArtifactValidationResult(root, None, tuple(issues))

        declared_files = _manifest_names(manifest, "artifact_files", issues, required=True)
        required_files = _manifest_names(manifest, "files", issues, required=False)
        optional_files = _manifest_names(manifest, "optional_files", issues, required=False)
        if declared_files is not None:
            _check_artifact_files(actual_files, declared_files, issues)
        _check_required_files(actual_files, required_files or [], issues)
        _check_optional_files(
            actual_files,
            set(declared_files or []),
            optional_files or [],
            issues,
        )
        if check_path:
            _check_run_path(root, manifest, issues)
        return ArtifactValidationResult(root, manifest, tuple(issues))


def _actual_files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def _load_manifest(
    path: Path,
    issues: list[ArtifactValidationIssue],
) -> dict[str, Any] | None:
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


def _manifest_names(
    manifest: Mapping[str, Any],
    field: str,
    issues: list[ArtifactValidationIssue],
    *,
    required: bool,
) -> list[str] | None:
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


def _is_safe_relative_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and name != "." and not path.is_absolute() and ".." not in path.parts


def _check_artifact_files(
    actual_files: list[str],
    declared_files: list[str],
    issues: list[ArtifactValidationIssue],
) -> None:
    actual = set(actual_files)
    declared = set(declared_files)
    for name in sorted(declared - actual):
        issues.append(
            ArtifactValidationIssue(
                "artifact_file_missing",
                f"Manifest 声明了文件，但目录中不存在: {name}",
                name,
            )
        )
    for name in sorted(actual - declared):
        issues.append(
            ArtifactValidationIssue(
                "artifact_file_unlisted",
                f"目录中存在未被 Manifest 声明的文件: {name}",
                name,
            )
        )


def _check_required_files(
    actual_files: list[str],
    required_files: list[str],
    issues: list[ArtifactValidationIssue],
) -> None:
    actual = set(actual_files)
    for name in sorted(set(required_files) - actual):
        issues.append(
            ArtifactValidationIssue(
                "required_file_missing",
                f"缺少必需文件: {name}",
                name,
            )
        )


def _check_optional_files(
    actual_files: list[str],
    declared_files: set[str],
    optional_files: list[str],
    issues: list[ArtifactValidationIssue],
) -> None:
    actual = set(actual_files)
    for name in sorted(set(optional_files)):
        present = name in actual
        declared = name in declared_files
        if present == declared:
            continue
        state = "存在但未列入 artifact_files" if present else "已列入 artifact_files 但实际不存在"
        issues.append(
            ArtifactValidationIssue(
                "optional_file_state_invalid",
                f"可选文件状态不一致: {name}（{state}）",
                name,
            )
        )


def _check_run_path(
    root: Path,
    manifest: Mapping[str, Any],
    issues: list[ArtifactValidationIssue],
) -> None:
    if root.parent.parent.name != "runs" or not root.parent.name.startswith("as_of="):
        return
    expected = {
        "run_id": root.name,
        "as_of_date": root.parent.name.removeprefix("as_of="),
        "artifact_type": root.parent.parent.parent.name,
    }
    for field, expected_value in expected.items():
        actual_value = manifest.get(field)
        if actual_value == expected_value:
            continue
        issues.append(
            ArtifactValidationIssue(
                "manifest_path_mismatch",
                f"Manifest 字段 {field}={actual_value!r} 与路径期望值 {expected_value!r} 不一致",
                field,
            )
        )


def _resolve_latest_source(
    manifest: Mapping[str, Any],
    issues: list[ArtifactValidationIssue],
) -> Path | None:
    artifact_root = manifest.get("artifact_root")
    as_of_date = manifest.get("as_of_date")
    run_id = manifest.get("run_id")
    if (
        not isinstance(artifact_root, str)
        or not artifact_root
        or not isinstance(as_of_date, str)
        or not as_of_date
        or not isinstance(run_id, str)
        or not run_id
    ):
        issues.append(
            ArtifactValidationIssue(
                "latest_source_missing",
                "latest Manifest 缺少定位源运行目录所需的 artifact_root、as_of_date 或 run_id",
            )
        )
        return None
    source_dir = Path(artifact_root) / "runs" / f"as_of={as_of_date}" / run_id
    if not source_dir.is_dir():
        issues.append(
            ArtifactValidationIssue(
                "latest_source_missing",
                f"latest 对应的源运行目录不存在: {source_dir}",
            )
        )
        return None
    return source_dir


def _check_latest_match(
    latest_dir: Path,
    source_dir: Path,
    latest_manifest: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    issues: list[ArtifactValidationIssue],
) -> None:
    for field in ("run_id", "as_of_date", "artifact_type"):
        if latest_manifest.get(field) == source_manifest.get(field):
            continue
        issues.append(
            ArtifactValidationIssue(
                "latest_manifest_mismatch",
                f"latest 与源运行目录的 Manifest 字段不一致: {field}",
                field,
            )
        )
    if set(_actual_files(latest_dir)) != set(_actual_files(source_dir)):
        issues.append(
            ArtifactValidationIssue(
                "latest_file_set_mismatch",
                "latest 与源运行目录的文件集合不一致",
            )
        )


__all__ = [
    "ArtifactValidationIssue",
    "ArtifactValidationResult",
    "ArtifactValidator",
]
