"""共享管线产物校验测试。"""

import json
from datetime import date
from pathlib import Path

import pytest

from stock_analytics.pipelines.artifact_store import ArtifactStore
from stock_analytics.pipelines.artifact_validator import ArtifactValidator


def _write_manifest(
    root: Path,
    *,
    artifact_files: list[str],
    files: dict[str, str] | None = None,
    optional_files: dict[str, str] | None = None,
    fields: dict[str, object] | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "artifact_files": artifact_files,
        **({"files": files} if files is not None else {}),
        **({"optional_files": optional_files} if optional_files is not None else {}),
        **(fields or {}),
    }
    (root / "manifest.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_validator_accepts_matching_artifact_files_and_absent_optional_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    (root / "report.md").parent.mkdir(parents=True)
    (root / "report.md").write_text("report", encoding="utf-8")
    _write_manifest(
        root,
        artifact_files=["manifest.json", "report.md"],
        files={"manifest": "manifest.json", "report": "report.md"},
        optional_files={"scored": "scored.parquet"},
    )

    result = ArtifactValidator().validate(root)

    assert result.valid
    assert result.status == "passed"
    assert result.issues == ()


def test_validator_reports_manifest_file_list_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "run"
    (root / "unexpected.txt").parent.mkdir(parents=True)
    (root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    _write_manifest(
        root,
        artifact_files=["manifest.json", "missing.txt"],
    )

    result = ArtifactValidator().validate(root)
    codes = {issue.code for issue in result.issues}

    assert not result.valid
    assert {"artifact_file_missing", "artifact_file_unlisted"} <= codes


def test_validator_reports_missing_required_file(tmp_path: Path) -> None:
    root = tmp_path / "run"
    _write_manifest(
        root,
        artifact_files=["manifest.json"],
        files={"manifest": "manifest.json", "report": "report.md"},
    )

    result = ArtifactValidator().validate(root)

    assert not result.valid
    assert any(
        issue.code == "required_file_missing" and issue.filename == "report.md"
        for issue in result.issues
    )


def test_validator_reports_inconsistent_optional_file_state(tmp_path: Path) -> None:
    root = tmp_path / "run"
    (root / "scored.parquet").parent.mkdir(parents=True)
    (root / "scored.parquet").write_bytes(b"not a real parquet file")
    _write_manifest(
        root,
        artifact_files=["manifest.json"],
        optional_files={"scored": "scored.parquet"},
    )

    result = ArtifactValidator().validate(root)

    assert not result.valid
    assert any(
        issue.code == "optional_file_state_invalid" and issue.filename == "scored.parquet"
        for issue in result.issues
    )


@pytest.mark.parametrize("field", ["run_id", "as_of_date", "artifact_type"])
def test_validator_reports_manifest_path_mismatch(tmp_path: Path, field: str) -> None:
    artifact_root = tmp_path / "market_temperature"
    root = artifact_root / "runs" / "as_of=2026-08-24" / "run_test"
    (root / "report.md").parent.mkdir(parents=True)
    (root / "report.md").write_text("report", encoding="utf-8")
    fields: dict[str, object] = {
        "run_id": "run_test",
        "as_of_date": "2026-08-24",
        "artifact_type": "market_temperature",
    }
    fields[field] = {
        "run_id": "run_other",
        "as_of_date": "2026-08-23",
        "artifact_type": "industry_structure",
    }[field]
    _write_manifest(
        root,
        artifact_files=["manifest.json", "report.md"],
        files={"manifest": "manifest.json", "report": "report.md"},
        fields={**fields, "artifact_root": str(artifact_root)},
    )

    result = ArtifactValidator().validate(root)

    assert not result.valid
    assert any(
        issue.code == "manifest_path_mismatch" and issue.filename == field
        for issue in result.issues
    )


def test_validator_accepts_latest_when_source_run_is_complete(tmp_path: Path) -> None:
    artifact_root = tmp_path / "market_temperature"
    paths = ArtifactStore.build_run_paths(
        date(2026, 8, 24),
        artifact_root,
        run_id="run_test",
        latest_root=tmp_path / "shared",
    )
    manifest = {
        "artifact_root": str(artifact_root),
        "artifact_type": "market_temperature",
        "as_of_date": "2026-08-24",
        "run_id": "run_test",
        "files": {"manifest": "manifest.json", "report": "report.md"},
    }
    with ArtifactStore(paths).transaction() as session:
        session.write_json("manifest.json", manifest)
        session.write_text("report.md", "report")

    result = ArtifactValidator().validate(paths.latest_dir)

    assert result.valid
    assert result.status == "passed"


def test_validator_rejects_latest_when_source_file_is_not_copied(tmp_path: Path) -> None:
    artifact_root = tmp_path / "market_temperature"
    paths = ArtifactStore.build_run_paths(date(2026, 8, 24), artifact_root, run_id="run_test")
    manifest = {
        "artifact_root": str(artifact_root),
        "artifact_type": "market_temperature",
        "as_of_date": "2026-08-24",
        "run_id": "run_test",
        "files": {"manifest": "manifest.json", "report": "report.md"},
    }
    with ArtifactStore(paths).transaction() as session:
        session.write_json("manifest.json", manifest)
        session.write_text("report.md", "report")
    paths.latest_dir.joinpath("report.md").unlink()

    result = ArtifactValidator().validate_latest(paths.latest_dir)
    codes = {issue.code for issue in result.issues}

    assert not result.valid
    assert "artifact_file_missing" in codes
