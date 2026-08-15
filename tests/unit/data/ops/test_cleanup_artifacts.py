"""数据产物清理工具测试。"""

import os
from pathlib import Path

from stock.data.ops.cleanup_artifacts import collect_candidates, delete_candidates, main


def _write_with_mtime(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"artifact")
    os.utime(path, (mtime, mtime))


def test_collect_candidates_filters_scope_and_age(tmp_path: Path) -> None:
    root = tmp_path / "data"
    old_backup = root / "raw" / "old.bak.parquet"
    old_temp = root / "raw" / "old.migration.tmp.parquet"
    fresh_backup = root / "raw" / "fresh.bak.parquet"
    regular = root / "curated" / "data.parquet"
    restore_dir = root / "audit" / "raw_unit_restore_20260815_120000"

    _write_with_mtime(old_backup, 100)
    _write_with_mtime(old_temp, 100)
    _write_with_mtime(fresh_backup, 900)
    _write_with_mtime(regular, 100)
    _write_with_mtime(restore_dir / "raw" / "data.parquet", 100)
    os.utime(restore_dir, (100, 100))

    candidates = collect_candidates(root, older_than_days=7, now=7 * 24 * 60 * 60 + 395)

    assert {(item.kind, item.path.relative_to(root).as_posix()) for item in candidates} == {
        ("backup", "raw/old.bak.parquet"),
        ("migration_tmp", "raw/old.migration.tmp.parquet"),
        ("restore_snapshot", "audit/raw_unit_restore_20260815_120000"),
    }


def test_delete_candidates_removes_only_stale_candidates(tmp_path: Path) -> None:
    root = tmp_path / "data"
    old_backup = root / "raw" / "old.bak.parquet"
    fresh_backup = root / "raw" / "fresh.bak.parquet"
    restore_dir = root / "audit" / "raw_unit_restore_20260815_120000"

    _write_with_mtime(old_backup, 100)
    _write_with_mtime(fresh_backup, 900)
    _write_with_mtime(restore_dir / "raw" / "data.parquet", 100)
    os.utime(restore_dir, (100, 100))

    candidates = collect_candidates(root, older_than_days=7, now=7 * 24 * 60 * 60 + 395)
    deleted, skipped = delete_candidates(candidates, root=root, cutoff=395)

    assert deleted == 2
    assert skipped == 0
    assert not old_backup.exists()
    assert not restore_dir.exists()
    assert fresh_backup.exists()


def test_main_defaults_to_preview(tmp_path: Path, capsys) -> None:
    root = tmp_path / "data"
    artifact = root / "raw" / "old.bak.parquet"
    _write_with_mtime(artifact, 0)

    assert main(["--root", str(root), "--older-than-days", "7"]) == 0

    assert artifact.exists()
    assert "预览模式" in capsys.readouterr().out
