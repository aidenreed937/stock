"""个股排雷产物测试。"""

import json
from datetime import date

import polars as pl

from stock_analytics.pipelines.stock_screen.artifacts import (
    StockScreenArtifactPayload,
    build_run_paths,
    write_artifacts,
)


def test_write_artifacts_creates_run_and_latest_files(tmp_path) -> None:
    paths = build_run_paths(date(2026, 8, 20), tmp_path / "stock_screen", run_id="run_test")
    table = pl.DataFrame({"symbol": ["000001.SZ"], "level": ["passed"]})
    payload = StockScreenArtifactPayload(
        manifest={
            "artifact_type": "stock_screen",
            "as_of_date": "2026-08-20",
            "run_id": "run_test",
        },
        excluded=table.clear(),
        warned=table.clear(),
        passed=table,
        scored=pl.DataFrame(),
        scores={"passed_count": 1},
        report_markdown="# report\n",
        report_json={"passed_count": 1},
        quality_report_markdown="# quality\n",
        quality_report_json={"status": "passed"},
    )

    write_artifacts(paths, payload)

    assert paths.run_dir.is_dir()
    assert paths.passed.exists()
    assert (paths.latest_dir / "passed.csv").exists()
    assert (paths.latest_dir / "quality_report.json").exists()
    persisted_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert "scored.parquet" not in persisted_manifest["artifact_files"]


def test_write_artifacts_persists_optional_scored_file(tmp_path) -> None:
    paths = build_run_paths(date(2026, 8, 20), tmp_path / "stock_screen", run_id="run_scored")
    table = pl.DataFrame({"symbol": ["000001.SZ"], "level": ["passed"]})
    payload = StockScreenArtifactPayload(
        manifest={
            "artifact_type": "stock_screen",
            "as_of_date": "2026-08-20",
            "run_id": "run_scored",
        },
        excluded=table.clear(),
        warned=table.clear(),
        passed=table,
        scored=pl.DataFrame({"symbol": ["000001.SZ"], "composite_score": [80.0]}),
        scores={"passed_count": 1},
        report_markdown="# report\n",
        report_json={"passed_count": 1},
        quality_report_markdown="# quality\n",
        quality_report_json={"status": "passed"},
    )

    write_artifacts(paths, payload)

    assert paths.scored.exists()
    persisted_manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert "scored.parquet" in persisted_manifest["artifact_files"]
    assert (paths.latest_dir / "scored.parquet").exists()
