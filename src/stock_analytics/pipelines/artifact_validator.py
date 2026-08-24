"""业务管线运行产物的 Manifest 与文件清单校验。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from stock_analytics.pipelines.artifact_validator_files import (
    ArtifactValidationIssue,
    actual_files,
    check_artifact_files,
    check_optional_files,
    check_required_files,
    load_manifest,
    manifest_names,
)


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


class ArtifactValidationError(RuntimeError):
    """产物校验失败异常。"""

    def __init__(self, result: ArtifactValidationResult) -> None:
        self.result = result
        details = "; ".join(issue.message for issue in result.issues[:5])
        if len(result.issues) > 5:
            details += f"；另有 {len(result.issues) - 5} 个问题"
        super().__init__(f"产物校验失败: {result.artifact_dir}: {details}")


class ArtifactValidator:
    """校验运行目录中的 Manifest、必需文件与可选文件状态。"""

    def validate(
        self,
        artifact_dir: Path | str,
        *,
        check_path: bool = True,
        expected_artifact_type: str | None = None,
    ) -> ArtifactValidationResult:
        """校验一个已发布的运行目录。"""
        root = Path(artifact_dir)
        if root.name == "latest" and check_path:
            return self.validate_latest(root, expected_artifact_type=expected_artifact_type)
        return self._validate_directory(
            root,
            check_path=check_path,
            expected_artifact_type=expected_artifact_type,
        )

    def validate_or_raise(
        self,
        artifact_dir: Path | str,
        *,
        check_path: bool = True,
        expected_artifact_type: str | None = None,
    ) -> ArtifactValidationResult:
        """校验产物，失败时抛出异常。"""
        result = self.validate(
            artifact_dir,
            check_path=check_path,
            expected_artifact_type=expected_artifact_type,
        )
        if not result.valid:
            raise ArtifactValidationError(result)
        return result

    def validate_latest(
        self,
        latest_dir: Path | str,
        *,
        source_dir: Path | str | None = None,
        expected_artifact_type: str | None = None,
    ) -> ArtifactValidationResult:
        """校验 latest 目录，并确认其对应的运行目录完整。"""
        root = Path(latest_dir)
        result = self._validate_directory(
            root,
            check_path=False,
            expected_artifact_type=expected_artifact_type,
        )
        issues = list(result.issues)
        if result.manifest is not None:
            resolved_source_dir = (
                Path(source_dir)
                if source_dir is not None
                else _resolve_latest_source(result.manifest, issues)
            )
            if resolved_source_dir is not None:
                source_result = self._validate_directory(
                    resolved_source_dir,
                    check_path=True,
                    expected_artifact_type=expected_artifact_type,
                )
                if not source_result.valid:
                    issues.append(
                        ArtifactValidationIssue(
                            "latest_source_invalid",
                            f"latest 对应的运行目录未通过校验: {resolved_source_dir}",
                        )
                    )
                elif source_result.manifest is not None:
                    _check_latest_match(
                        root,
                        resolved_source_dir,
                        result.manifest,
                        source_result.manifest,
                        issues,
                    )
        return ArtifactValidationResult(root, result.manifest, tuple(issues))

    def validate_latest_or_raise(
        self,
        latest_dir: Path | str,
        *,
        source_dir: Path | str | None = None,
        expected_artifact_type: str | None = None,
    ) -> ArtifactValidationResult:
        """校验 latest 及其源运行目录，失败时抛出异常。"""
        result = self.validate_latest(
            latest_dir,
            source_dir=source_dir,
            expected_artifact_type=expected_artifact_type,
        )
        if not result.valid:
            raise ArtifactValidationError(result)
        return result

    def _validate_directory(
        self,
        root: Path,
        *,
        check_path: bool,
        expected_artifact_type: str | None,
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

        actual = set(actual_files(root))
        manifest = load_manifest(root / "manifest.json", issues)
        if manifest is None:
            return ArtifactValidationResult(root, None, tuple(issues))

        if expected_artifact_type is not None:
            _check_artifact_type(manifest, expected_artifact_type, issues)
        declared_files = manifest_names(manifest, "artifact_files", issues, required=True)
        required_files = manifest_names(manifest, "files", issues, required=False)
        optional_files = manifest_names(manifest, "optional_files", issues, required=False)
        if declared_files is not None:
            check_artifact_files(actual, declared_files, issues)
        check_required_files(actual, required_files or [], issues)
        check_optional_files(
            actual,
            set(declared_files or []),
            optional_files or [],
            issues,
        )
        if check_path:
            _check_run_path(root, manifest, issues)
        return ArtifactValidationResult(root, manifest, tuple(issues))


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


def _check_artifact_type(
    manifest: Mapping[str, Any],
    expected_artifact_type: str,
    issues: list[ArtifactValidationIssue],
) -> None:
    actual_artifact_type = manifest.get("artifact_type")
    if actual_artifact_type == expected_artifact_type:
        return
    issues.append(
        ArtifactValidationIssue(
            "manifest_artifact_type_mismatch",
            f"Manifest artifact_type={actual_artifact_type!r} 与期望值 "
            f"{expected_artifact_type!r} 不一致",
            "artifact_type",
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
    if set(actual_files(latest_dir)) != set(actual_files(source_dir)):
        issues.append(
            ArtifactValidationIssue(
                "latest_file_set_mismatch",
                "latest 与源运行目录的文件集合不一致",
            )
        )


__all__ = [
    "ArtifactValidationError",
    "ArtifactValidationIssue",
    "ArtifactValidationResult",
    "ArtifactValidator",
]
