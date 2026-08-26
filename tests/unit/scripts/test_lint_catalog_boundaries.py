"""Catalog 物理读取边界检查脚本测试。"""

from pathlib import Path

from scripts.lint_catalog_boundaries import check_file, main


def test_catalog_boundary_lint_passes_for_current_business_layers() -> None:
    assert main() == 0


def test_catalog_boundary_lint_rejects_direct_curated_scan(tmp_path: Path) -> None:
    path = tmp_path / "bad.py"
    path.write_text(
        "from pathlib import Path\nPath('data/curated').rglob('*.parquet')\n",
        encoding="utf-8",
    )

    violations = check_file(path)

    assert len(violations) == 1
    assert "rglob" in violations[0].message
