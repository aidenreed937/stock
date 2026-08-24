"""运行产物索引测试。"""

import json
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.artifact_index import read_run_index, rebuild_run_index
from stock_analytics.pipelines.artifact_store import ArtifactRunPaths, ArtifactStore


def _manifest(paths: ArtifactRunPaths) -> dict[str, str]:
    run_dir = paths.run_dir
    return {
        "artifact_type": "market_temperature",
        "as_of_date": run_dir.parent.name.removeprefix("as_of="),
        "run_id": run_dir.name,
    }


def test_store_rebuilds_index_for_each_published_run(tmp_path: Path) -> None:
    first = ArtifactStore.build_run_paths(date(2026, 8, 23), tmp_path, run_id="run_first")
    second = ArtifactStore.build_run_paths(
        date(2026, 8, 24),
        tmp_path,
        run_id="run_second",
        run_class="backfill",
    )
    for paths in (first, second):
        with ArtifactStore(paths).transaction(update_latest=False) as session:
            session.write_json("manifest.json", _manifest(paths))
            session.write_text("report.md", paths.run_dir.name)

    index = read_run_index(tmp_path)

    assert index is not None
    assert [item["run_id"] for item in index["runs"]] == ["run_first", "run_second"]
    assert index["runs"][1]["run_class"] == "backfill"


def test_rebuild_index_skips_invalid_run_manifest(tmp_path: Path) -> None:
    valid = tmp_path / "runs" / "as_of=2026-08-24" / "run_valid"
    invalid = tmp_path / "runs" / "as_of=2026-08-24" / "run_invalid"
    valid.mkdir(parents=True)
    invalid.mkdir()
    (valid / "manifest.json").write_text(
        json.dumps(
            {
                "artifact_type": "market_temperature",
                "as_of_date": "2026-08-24",
                "run_id": "run_valid",
                "artifact_files": ["manifest.json"],
            }
        ),
        encoding="utf-8",
    )
    (invalid / "manifest.json").write_text("not json", encoding="utf-8")

    payload = rebuild_run_index(tmp_path)

    assert [item["run_id"] for item in payload["runs"]] == ["run_valid"]
