"""Features CLI 目标路由测试。"""

from pathlib import Path

import polars as pl

from stock_cli import features


def test_features_cli_builds_domain_marts(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, object]] = []

    class _Catalog:
        pass

    class _Store:
        pass

    class _Builder:
        def __init__(self, **kwargs: object) -> None:
            calls.append(("init", kwargs))

        def build_all(self, **kwargs: object) -> dict[str, pl.DataFrame]:
            calls.append(("build_all", kwargs))
            return {"convertible_bond_daily": pl.DataFrame({"trade_date": []})}

    monkeypatch.setattr(features, "DataCatalog", lambda **_: _Catalog())
    monkeypatch.setattr(features, "FeatureStore", lambda **_: _Store())
    monkeypatch.setattr(features, "DomainMartBuilder", _Builder)
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

    assert calls[0][0] == "init"
    assert calls[1] == (
        "build_all",
        {
            "start_date": features.date(2026, 8, 1),
            "end_date": features.date(2026, 8, 2),
            "overwrite": False,
        },
    )
