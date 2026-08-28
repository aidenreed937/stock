from datetime import date

import polars as pl

from stock_analytics.pipelines.artifacts.reader import ArtifactRun
from stock_analytics.pipelines.macro_risk import artifacts as artifacts_mod


def test_load_latest_risk_factors(monkeypatch, tmp_path) -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "overheat_index": [50.0, 51.0],
            "panic_index": [40.0, 39.0],
        }
    )
    frame.write_parquet(tmp_path / "risk_factors.parquet")
    run = ArtifactRun(tmp_path, tmp_path, {"artifact_type": "macro_risk"})
    monkeypatch.setattr(
        artifacts_mod,
        "resolve_artifact_run",
        lambda root, **kwargs: run,
    )

    run_dir, out_frame, manifest = artifacts_mod.load_latest_risk_factors(str(tmp_path))

    assert run_dir == tmp_path
    assert out_frame["overheat_index"].to_list() == [50.0, 51.0]
    assert out_frame["panic_index"].to_list() == [40.0, 39.0]
    assert manifest["artifact_type"] == "macro_risk"
