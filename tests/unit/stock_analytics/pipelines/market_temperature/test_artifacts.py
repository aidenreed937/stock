"""市场温度计产物写入测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.market_temperature.artifacts import (
    MarketTemperatureArtifactPayload,
    build_run_paths,
    write_artifacts,
)


def test_write_artifacts_updates_run_and_latest(tmp_path) -> None:
    paths = build_run_paths(date(2026, 8, 14), tmp_path, run_id="run_test")
    facts = pl.DataFrame(
        {
            "fact_id": ["window_20d"],
            "category": ["analysis_window"],
            "dimension": ["meta"],
            "data_source": ["tushare"],
            "dataset": ["stock_daily_bar"],
            "as_of_date": [date(2026, 8, 14)],
            "window": [20],
            "metric_id": ["window_20d"],
            "value_float": [None],
            "value_text": ["2026-07-20..2026-08-14"],
            "unit": [""],
            "sample_size": [20],
            "source": ["test"],
            "status": ["ok"],
            "note": [""],
        }
    )

    write_artifacts(
        paths,
        MarketTemperatureArtifactPayload(
            manifest={"as_of_date": "2026-08-14"},
            facts=facts,
            scores={"composite": {"temperature": None}},
            report_markdown="# report\n",
            report_json={"title": "report"},
            human_report_markdown="# human report\n",
            quality_report_markdown="# quality report\n",
            quality_report_json={"title": "quality"},
        ),
    )

    assert paths.manifest.exists()
    assert paths.facts.exists()
    assert paths.scores.exists()
    assert paths.report_md.exists()
    assert paths.human_report_md.exists()
    assert paths.quality_report_md.exists()
    assert paths.quality_report_json.exists()
    assert (paths.latest_dir / "manifest.json").exists()
    assert (paths.latest_dir / "facts.parquet").exists()
    assert (paths.latest_dir / "human_report.md").exists()
    assert (paths.latest_dir / "quality_report.md").exists()
