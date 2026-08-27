"""分析产物定位与 Manifest 校验测试。"""

import json
from datetime import date
from pathlib import Path

import pytest

from stock_analytics.pipelines.artifacts import (
    ArtifactUnavailableError,
    resolve_artifact_run,
)


def _write_run(
    root: Path,
    *,
    as_of_date: str = "2026-08-20",
    run_id: str = "run_0001",
    run_class: str = "official",
) -> Path:
    run_dir = root / "runs" / f"as_of={as_of_date}" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "scores.json").write_text("{}", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artifact_type": "market_temperature",
                "artifact_root": str(root),
                "run_id": run_id,
                "as_of_date": as_of_date,
                "run_class": run_class,
                "artifact_files": ["manifest.json", "scores.json"],
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_resolve_artifact_run_validates_date_and_reads_json(tmp_path: Path) -> None:
    root = tmp_path / "market_temperature"
    _write_run(root)

    run = resolve_artifact_run(
        root,
        as_of_date=date(2026, 8, 20),
        expected_artifact_type="market_temperature",
    )

    assert run.manifest["run_id"] == "run_0001"
    assert run.read_json("scores.json") == {}


def test_resolve_artifact_run_fails_when_manifest_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "market_temperature"
    run_dir = _write_run(root)
    (run_dir / "manifest.json").unlink()

    with pytest.raises(ArtifactUnavailableError, match="产物不可用"):
        resolve_artifact_run(
            root,
            as_of_date=date(2026, 8, 20),
            expected_artifact_type="market_temperature",
        )


def test_resolve_artifact_run_fails_when_requested_date_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "market_temperature"
    _write_run(root)

    with pytest.raises(ArtifactUnavailableError, match="缺少 market_temperature 产物运行"):
        resolve_artifact_run(
            root,
            as_of_date=date(2026, 8, 21),
            expected_artifact_type="market_temperature",
        )


def test_resolve_artifact_run_selects_requested_run_class(tmp_path: Path) -> None:
    root = tmp_path / "market_temperature"
    _write_run(root, run_id="run_official", run_class="official")
    _write_run(root, run_id="run_backfill", run_class="backfill")

    run = resolve_artifact_run(
        root,
        as_of_date=date(2026, 8, 20),
        expected_artifact_type="market_temperature",
        expected_run_class="backfill",
    )

    assert run.manifest["run_id"] == "run_backfill"
