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


def test_features_cli_accepts_settlement_iv_proxy_target(monkeypatch) -> None:
    build = MagicMock()
    monkeypatch.setattr(features, "build_features", build)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stock_cli.features",
            "build",
            "--target",
            "settlement_iv_proxy_daily",
            "--start",
            "2026-10-09",
            "--end",
            "2026-10-09",
        ],
    )

    features.main()

    build.assert_called_once_with(
        target="settlement_iv_proxy_daily",
        start_date=features.date(2026, 10, 9),
        end_date=features.date(2026, 10, 9),
        overwrite=False,
        storage_dir=None,
    )


def test_features_cli_accepts_smart_money_target(monkeypatch) -> None:
    build = MagicMock()
    monkeypatch.setattr(features, "build_features", build)
    monkeypatch.setattr(
        "sys.argv",
        [
            "stock_cli.features",
            "build",
            "--target",
            "smart_money_daily",
            "--start",
            "2026-10-09",
            "--end",
            "2026-10-09",
        ],
    )

    features.main()

    build.assert_called_once_with(
        target="smart_money_daily",
        start_date=features.date(2026, 10, 9),
        end_date=features.date(2026, 10, 9),
        overwrite=False,
        storage_dir=None,
    )
