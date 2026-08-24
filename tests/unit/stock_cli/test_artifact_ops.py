"""产物索引与清理 CLI 测试。"""

import json
import os
from pathlib import Path

from stock_cli.artifact_ops import main


def _write_run(root: Path) -> Path:
    run_dir = root / "runs" / "as_of=2026-08-20" / "run_old"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "artifact_type": "market_temperature",
                "as_of_date": "2026-08-20",
                "run_id": "run_old",
                "run_class": "backfill",
                "artifact_files": ["manifest.json"],
            }
        ),
        encoding="utf-8",
    )
    os.utime(run_dir, (0, 0))
    return run_dir


def test_index_and_cleanup_cli_preview_then_apply(tmp_path: Path, capsys) -> None:
    root = tmp_path / "market_temperature"
    run_dir = _write_run(root)

    assert main(["index", "--root", str(root)]) == 0
    assert (
        main(
            [
                "cleanup",
                "--root",
                str(root),
                "--older-than-days",
                "0",
                "--run-class",
                "backfill",
            ]
        )
        == 0
    )
    assert run_dir.exists()
    assert "预览模式" in capsys.readouterr().out

    assert (
        main(
            [
                "cleanup",
                "--root",
                str(root),
                "--older-than-days",
                "0",
                "--run-class",
                "backfill",
                "--apply",
            ]
        )
        == 0
    )
    assert not run_dir.exists()
