"""共享管线产物存储测试。"""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import stock_analytics.pipelines.artifact_store as artifact_store_module
from stock_analytics.pipelines.artifact_index import INDEX_FILENAME
from stock_analytics.pipelines.artifact_store import (
    ArtifactRunPaths,
    ArtifactStore,
    ArtifactWriteSession,
)
from stock_analytics.pipelines.artifact_validator import ArtifactValidationError, ArtifactValidator


def _manifest(paths: ArtifactRunPaths) -> dict[str, str]:
    return {
        "artifact_type": paths.root.name,
        "as_of_date": paths.run_dir.parent.name.removeprefix("as_of="),
        "run_id": paths.run_dir.name,
    }


def test_build_run_paths_supports_separate_latest_root(tmp_path: Path) -> None:
    paths = ArtifactStore.build_run_paths(
        date(2026, 8, 24),
        tmp_path / "quant_brief",
        run_id="run_test",
        latest_root=tmp_path / "shared",
    )

    assert paths.root == tmp_path / "quant_brief"
    assert paths.run_dir == tmp_path / "quant_brief/runs/as_of=2026-08-24/run_test"
    assert paths.latest_dir == tmp_path / "shared/latest"


def test_transaction_publishes_run_and_latest_atomically(tmp_path: Path) -> None:
    paths = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_test")

    with ArtifactStore(paths).transaction() as session:
        session.write_json("manifest.json", _manifest(paths))
        session.write_parquet("facts.parquet", pl.DataFrame({"value": [1]}))
        session.write_text("report.md", "# report\n")

    manifest = paths.run_dir / "manifest.json"
    facts = paths.run_dir / "facts.parquet"
    assert json.loads(manifest.read_text(encoding="utf-8"))["as_of_date"] == "2026-08-24"
    assert facts.exists()
    persisted = json.loads(manifest.read_text(encoding="utf-8"))
    assert persisted["run_class"] == "official"
    assert persisted["artifact_integrity"]["facts.parquet"]["bytes"] == facts.stat().st_size
    assert len(persisted["artifact_integrity"]["facts.parquet"]["sha256"]) == 64
    assert paths.latest_dir.joinpath("manifest.json").exists()
    assert paths.latest_dir.joinpath("facts.parquet").exists()
    index = json.loads((tmp_path / INDEX_FILENAME).read_text(encoding="utf-8"))
    assert index["runs"][0]["run_id"] == "run_test"
    assert list(paths.run_dir.parent.glob(".run_test.*")) == []


def test_latest_replaces_previous_file_set(tmp_path: Path) -> None:
    first = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_first")
    with ArtifactStore(first).transaction() as session:
        session.write_json("manifest.json", _manifest(first))
        session.write_text("optional.txt", "stale")

    second = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_second")
    with ArtifactStore(second).transaction() as session:
        session.write_json("manifest.json", _manifest(second))

    assert (
        json.loads(second.latest_dir.joinpath("manifest.json").read_text(encoding="utf-8"))[
            "run_id"
        ]
        == "run_second"
    )
    assert not second.latest_dir.joinpath("optional.txt").exists()
    assert list(second.latest_dir.parent.glob(".latest.*")) == []


def test_transaction_can_skip_latest_publication(tmp_path: Path) -> None:
    paths = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_test")

    with ArtifactStore(paths).transaction(update_latest=False) as session:
        session.write_json("manifest.json", _manifest(paths))

    assert paths.run_dir.joinpath("manifest.json").exists()
    assert not paths.latest_dir.exists()


def test_default_run_ids_are_unique_at_subsecond_concurrency(tmp_path: Path) -> None:
    first = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path)
    second = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path)

    assert first.run_dir != second.run_dir
    assert first.run_dir.name.startswith("run_")


def test_run_class_is_persisted_and_integrity_detects_tampering(tmp_path: Path) -> None:
    paths = ArtifactStore.build_run_paths(
        date(2026, 8, 24),
        tmp_path,
        run_id="run_experiment",
        run_class="experiment",
    )
    with ArtifactStore(paths).transaction() as session:
        session.write_json("manifest.json", _manifest(paths))
        session.write_text("report.md", "original")

    manifest = json.loads(paths.run_dir.joinpath("manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_class"] == "experiment"
    paths.run_dir.joinpath("report.md").write_text("tampered", encoding="utf-8")

    result = ArtifactValidator().validate(paths.run_dir)

    assert not result.valid
    assert any(issue.code == "artifact_integrity_mismatch" for issue in result.issues)


def test_latest_restore_failure_preserves_backup_and_rolls_back_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_first")
    with ArtifactStore(first).transaction() as session:
        session.write_json("manifest.json", _manifest(first))

    second = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_second")
    original_replace = artifact_store_module.os.replace

    def _fail_latest_replacements(source: Path, destination: Path) -> None:
        if Path(destination) == second.latest_dir:
            raise OSError("latest replace failed")
        original_replace(source, destination)

    monkeypatch.setattr(artifact_store_module.os, "replace", _fail_latest_replacements)

    with pytest.raises(RuntimeError, match="备份保留在"):
        with ArtifactStore(second).transaction() as session:
            session.write_json("manifest.json", _manifest(second))

    backups = list(second.latest_dir.parent.glob(".latest.old-*"))
    assert not second.run_dir.exists()
    assert not second.latest_dir.exists()
    assert len(backups) == 1
    assert (
        json.loads(backups[0].joinpath("manifest.json").read_text(encoding="utf-8"))["run_id"]
        == "run_first"
    )


def test_latest_failure_rolls_back_run_and_allows_same_run_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_test")
    original_publish_latest = ArtifactWriteSession._publish_latest

    def _fail_publish_latest(self: ArtifactWriteSession) -> None:
        raise OSError("latest publish failed")

    monkeypatch.setattr(ArtifactWriteSession, "_publish_latest", _fail_publish_latest)
    with pytest.raises(OSError, match="latest publish failed"):
        with ArtifactStore(paths).transaction() as session:
            session.write_json("manifest.json", _manifest(paths))

    assert not paths.run_dir.exists()

    monkeypatch.setattr(ArtifactWriteSession, "_publish_latest", original_publish_latest)
    with ArtifactStore(paths).transaction() as session:
        session.write_json("manifest.json", _manifest(paths))

    assert json.loads(paths.run_dir.joinpath("manifest.json").read_text(encoding="utf-8"))[
        "run_id"
    ] == ("run_test")
    assert (
        json.loads(paths.latest_dir.joinpath("manifest.json").read_text(encoding="utf-8"))["run_id"]
        == "run_test"
    )


def test_failed_transaction_cleans_staging_without_publishing(tmp_path: Path) -> None:
    paths = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_test")

    def _write_and_fail() -> None:
        with ArtifactStore(paths).transaction() as session:
            session.write_text("partial.txt", "partial")
            raise RuntimeError("stop")

    with pytest.raises(RuntimeError, match="stop"):
        _write_and_fail()

    assert not paths.run_dir.exists()
    assert not paths.latest_dir.exists()
    assert list(paths.run_dir.parent.glob(".run_test.*")) == []


def test_validation_failure_does_not_publish_or_replace_latest(tmp_path: Path) -> None:
    first = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_first")
    with ArtifactStore(first).transaction() as session:
        session.write_json("manifest.json", _manifest(first))
        session.write_text("report.md", "first")

    second = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_second")
    invalid_manifest = {
        **_manifest(second),
        "files": {"required_report": "required.txt"},
    }
    with pytest.raises(ArtifactValidationError, match="缺少必需文件"):
        with ArtifactStore(second).transaction() as session:
            session.write_json("manifest.json", invalid_manifest)

    assert not second.run_dir.exists()
    assert (
        json.loads(first.latest_dir.joinpath("manifest.json").read_text(encoding="utf-8"))["run_id"]
        == "run_first"
    )


def test_latest_staging_validation_failure_rolls_back_new_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_test")
    original_copy2 = artifact_store_module.shutil.copy2

    def _skip_report_copy(source: Path, destination: Path, *args: object, **kwargs: object) -> str:
        if Path(source).name == "report.md":
            return str(destination)
        return original_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr(artifact_store_module.shutil, "copy2", _skip_report_copy)

    def _write_artifacts() -> None:
        with ArtifactStore(paths).transaction() as session:
            session.write_json("manifest.json", _manifest(paths))
            session.write_text("report.md", "report")

    with pytest.raises(ArtifactValidationError, match="Manifest 声明了文件"):
        _write_artifacts()

    assert not paths.run_dir.exists()
    assert not paths.latest_dir.exists()


def test_validation_supports_relative_root_and_separate_latest_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    paths = ArtifactStore.build_run_paths(
        date(2026, 8, 24),
        Path("analytics") / "market_temperature",
        run_id="run_test",
        latest_root=Path("shared") / "market_temperature",
    )

    with ArtifactStore(paths).transaction() as session:
        session.write_json("manifest.json", _manifest(paths))
        session.write_text("report.md", "report")

    assert paths.run_dir.exists()
    assert paths.latest_dir.exists()
