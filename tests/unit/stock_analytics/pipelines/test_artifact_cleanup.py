"""运行产物安全清理测试。"""

import json
import os
from pathlib import Path

import pytest

from stock_analytics.pipelines.artifact_cleanup import (
    collect_run_candidates,
    delete_run_candidates,
)


def _write_run(root: Path, as_of_date: str, run_id: str, run_class: str, mtime: float) -> Path:
    run_dir = root / "runs" / f"as_of={as_of_date}" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artifact_type": "market_temperature",
                "as_of_date": as_of_date,
                "run_id": run_id,
                "run_class": run_class,
                "artifact_files": ["manifest.json"],
            }
        ),
        encoding="utf-8",
    )
    os.utime(run_dir, (mtime, mtime))
    return run_dir


def test_collect_candidates_filters_class_and_protects_latest(tmp_path: Path) -> None:
    root = tmp_path / "market_temperature"
    _write_run(root, "2026-08-20", "run_official", "official", 100)
    _write_run(root, "2026-08-21", "run_experiment", "experiment", 100)
    _write_run(root, "2026-08-22", "run_latest", "official", 100)
    latest = root / "latest"
    latest.mkdir()
    (latest / "manifest.json").write_text(
        json.dumps({"as_of_date": "2026-08-22", "run_id": "run_latest"}),
        encoding="utf-8",
    )

    candidates = collect_run_candidates(
        root,
        older_than_days=1,
        run_class="official",
        now=100 + 2 * 24 * 60 * 60,
    )

    assert [item.run_id for item in candidates] == ["run_official"]


def test_delete_candidates_removes_only_controlled_runs(tmp_path: Path) -> None:
    root = tmp_path / "market_temperature"
    old_run = _write_run(root, "2026-08-20", "run_old", "backfill", 100)
    candidates = collect_run_candidates(root, older_than_days=1, now=100 + 2 * 24 * 60 * 60)

    deleted, skipped = delete_run_candidates(
        candidates,
        root=root,
        cutoff=100 + 24 * 60 * 60,
    )

    assert (deleted, skipped) == (1, 0)
    assert not old_run.exists()


def test_cleanup_refuses_to_scan_broken_latest(tmp_path: Path) -> None:
    root = tmp_path / "market_temperature"
    _write_run(root, "2026-08-20", "run_old", "official", 100)
    latest = root / "latest"
    latest.mkdir(parents=True)
    (latest / "manifest.json").write_text("broken", encoding="utf-8")

    with pytest.raises(ValueError, match="latest Manifest"):
        collect_run_candidates(root, older_than_days=1, now=100 + 2 * 24 * 60 * 60)
