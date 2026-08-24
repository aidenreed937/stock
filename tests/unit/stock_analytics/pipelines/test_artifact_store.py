"""共享管线产物存储测试。"""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import stock_analytics.pipelines.artifact_store as artifact_store_module
from stock_analytics.pipelines.artifact_store import ArtifactStore, ArtifactWriteSession


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
        session.write_json("manifest.json", {"as_of_date": date(2026, 8, 24)})
        session.write_parquet("facts.parquet", pl.DataFrame({"value": [1]}))
        session.write_text("report.md", "# report\n")

    manifest = paths.run_dir / "manifest.json"
    facts = paths.run_dir / "facts.parquet"
    assert json.loads(manifest.read_text(encoding="utf-8"))["as_of_date"] == "2026-08-24"
    assert facts.exists()
    assert paths.latest_dir.joinpath("manifest.json").exists()
    assert paths.latest_dir.joinpath("facts.parquet").exists()
    assert list(paths.run_dir.parent.glob(".run_test.*")) == []


def test_latest_replaces_previous_file_set(tmp_path: Path) -> None:
    first = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_first")
    with ArtifactStore(first).transaction() as session:
        session.write_text("manifest.json", "first")
        session.write_text("optional.txt", "stale")

    second = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_second")
    with ArtifactStore(second).transaction() as session:
        session.write_text("manifest.json", "second")

    assert second.latest_dir.joinpath("manifest.json").read_text(encoding="utf-8") == "second"
    assert not second.latest_dir.joinpath("optional.txt").exists()
    assert list(second.latest_dir.parent.glob(".latest.*")) == []


def test_transaction_can_skip_latest_publication(tmp_path: Path) -> None:
    paths = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_test")

    with ArtifactStore(paths).transaction(update_latest=False) as session:
        session.write_text("manifest.json", "run")

    assert paths.run_dir.joinpath("manifest.json").exists()
    assert not paths.latest_dir.exists()


def test_latest_restore_failure_preserves_backup_and_rolls_back_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_first")
    with ArtifactStore(first).transaction() as session:
        session.write_text("manifest.json", "first")

    second = ArtifactStore.build_run_paths(date(2026, 8, 24), tmp_path, run_id="run_second")
    original_replace = artifact_store_module.os.replace

    def _fail_latest_replacements(source: Path, destination: Path) -> None:
        if Path(destination) == second.latest_dir:
            raise OSError("latest replace failed")
        original_replace(source, destination)

    monkeypatch.setattr(artifact_store_module.os, "replace", _fail_latest_replacements)

    with pytest.raises(RuntimeError, match="备份保留在"):
        with ArtifactStore(second).transaction() as session:
            session.write_text("manifest.json", "second")

    backups = list(second.latest_dir.parent.glob(".latest.old-*"))
    assert not second.run_dir.exists()
    assert not second.latest_dir.exists()
    assert len(backups) == 1
    assert backups[0].joinpath("manifest.json").read_text(encoding="utf-8") == "first"


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
            session.write_text("manifest.json", "first attempt")

    assert not paths.run_dir.exists()

    monkeypatch.setattr(ArtifactWriteSession, "_publish_latest", original_publish_latest)
    with ArtifactStore(paths).transaction() as session:
        session.write_text("manifest.json", "retry")

    assert paths.run_dir.joinpath("manifest.json").read_text(encoding="utf-8") == "retry"
    assert paths.latest_dir.joinpath("manifest.json").read_text(encoding="utf-8") == "retry"


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
