"""Features CLI 目标路由测试。"""

from pathlib import Path
from unittest.mock import MagicMock

from stock_cli import features


def test_features_cli_builds_domain_marts(monkeypatch, tmp_path: Path) -> None:
    build = MagicMock()
    monkeypatch.setattr(features, "build_features", build)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stock_cli.features",
            "build",
            "--target",
            "domain_marts",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-02",
            "--storage-dir",
            str(tmp_path),
        ],
    )

    features.main()

    build.assert_called_once_with(
        target="domain_marts",
        start_date=features.date(2026, 8, 1),
        end_date=features.date(2026, 8, 2),
        overwrite=False,
        storage_dir=tmp_path,
    )
