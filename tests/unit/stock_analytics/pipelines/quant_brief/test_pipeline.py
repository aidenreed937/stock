"""量化投研简报管线测试。"""

import json
from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.quant_brief import run_quant_brief


def test_run_quant_brief_reads_upstream_artifacts_and_writes_four_step_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    as_of_date = date(2026, 8, 14)
    analytics_root = tmp_path / "data" / "analytics"
    market_run = analytics_root / "market_temperature" / "runs" / "as_of=2026-08-14" / "run_market"
    industry_run = (
        analytics_root / "industry_structure" / "runs" / "as_of=2026-08-14" / "run_industry"
    )
    market_run.mkdir(parents=True)
    industry_run.mkdir(parents=True)

    _write_json(
        market_run / "manifest.json",
        {"as_of_date": "2026-08-14", "run_id": "run_market"},
    )
    _write_json(
        market_run / "scores.json",
        {
            "composite": {"temperature": 55.0},
            "systemic_risk": {"level": "中等", "status": "moderate_systemic_risk"},
            "drivers": {"status": "no_comparison"},
            "dimensions": [
                {"dimension_id": "technical", "temperature": 62.0},
                {"dimension_id": "fund_flow", "temperature": 45.0},
                {"dimension_id": "valuation", "temperature": 55.0},
                {"dimension_id": "sentiment", "temperature": 52.0},
            ],
        },
    )
    pl.DataFrame(
        {
            "category": ["metric_value"] * 3,
            "dimension": ["sentiment", "fund_flow", "fund_flow"],
            "metric_id": [
                "amount_top_5pct_share",
                "margin_balance_growth_20d",
                "margin_balance_growth_60d",
            ],
            "value_float": [0.55, -0.01, 0.02],
            "metric_date": [as_of_date] * 3,
            "as_of_date": [as_of_date] * 3,
            "sample_size": [100, 1, 1],
            "status": ["ok"] * 3,
        }
    ).write_parquet(market_run / "facts.parquet")

    _write_json(
        industry_run / "manifest.json",
        {"as_of_date": "2026-08-14", "run_id": "run_industry"},
    )
    _write_json(
        industry_run / "scores.json",
        {
            "structure_health": {
                "crowded_industry_share": 35.0,
                "positive_return_20d_count": 25,
                "positive_return_60d_count": 8,
                "scored_industry_count": 31,
            },
            "trend_diagnostics": {
                "positive_return_20d_count": 25,
                "positive_return_60d_count": 8,
                "scored_industry_count": 31,
            },
        },
    )
    pl.DataFrame(
        [
            {
                "industry_code": "801950",
                "industry_name": "煤炭",
                "status": "ok",
                "structure_score": 72.0,
                "structure_rank": 1,
                "momentum_score": 75.0,
                "valuation_score": 70.0,
                "fundamental_score": 65.0,
                "fund_flow_score": 80.0,
                "money_net_inflow_share_20d": 0.2,
                "return_20d": 0.1,
                "return_60d": 0.2,
                "crowding_temperature": 40.0,
                "tcr": 3.0,
                "tags": "资金确认",
            },
            {
                "industry_code": "801760",
                "industry_name": "通信",
                "status": "ok",
                "structure_score": 45.0,
                "structure_rank": 31,
                "momentum_score": 50.0,
                "valuation_score": 45.0,
                "fundamental_score": 35.0,
                "fund_flow_score": 30.0,
                "money_net_inflow_share_20d": -0.2,
                "return_20d": -0.1,
                "return_60d": -0.2,
                "crowding_temperature": 85.0,
                "tcr": 4.2,
                "tags": "拥挤风险",
            },
        ]
    ).write_parquet(industry_run / "industry_panel.parquet")

    investor_latest_dir = analytics_root / "investor_brief" / "latest"
    investor_latest_dir.mkdir(parents=True)
    (investor_latest_dir / "brief_report.md").write_text("investor brief", encoding="utf-8")
    (investor_latest_dir / "brief_report.json").write_text("{}", encoding="utf-8")
    (investor_latest_dir / "manifest.json").write_text("investor manifest", encoding="utf-8")

    result = run_quant_brief(
        target_date=as_of_date,
        output_root=analytics_root / "quant_brief",
    )

    assert result.as_of_date == as_of_date
    assert result.manifest["artifact_type"] == "quant_brief"
    assert result.manifest["manifest_schema_version"] == 1
    assert result.manifest["provenance"]["config_sha256"]
    assert result.manifest["parents"]["industry_structure"]["run_id"] == "run_industry"
    assert set(result.manifest["artifact_files"]) == {
        "manifest.json",
        "brief_report.md",
        "brief_report.json",
    }
    assert result.paths.manifest.exists()
    assert result.paths.brief_md.exists()
    assert result.paths.brief_json.exists()
    latest_dir = analytics_root / "quant_brief" / "latest"
    assert result.paths.latest_dir == latest_dir
    assert (latest_dir / "manifest.json").exists()
    assert (latest_dir / "brief_report.md").exists()
    assert (latest_dir / "brief_report.json").exists()
    assert (investor_latest_dir / "brief_report.md").read_text(encoding="utf-8") == "investor brief"
    assert (investor_latest_dir / "brief_report.json").read_text(encoding="utf-8") == "{}"
    assert (investor_latest_dir / "manifest.json").read_text(
        encoding="utf-8"
    ) == "investor manifest"
    assert result.manifest["inputs"]["market_temperature"]["run_id"] == "run_market"
    assert result.brief_json["veto"]["top5pct"]["value"] == 0.55
    assert result.brief_json["sector"]["priority"][0]["industry_name"] == "煤炭"
    assert "## 3. 微观排雷与一票否决" in result.brief_markdown


def test_run_quant_brief_passes_through_upstream_drivers_and_margin_series(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    as_of_date = date(2026, 8, 14)
    analytics_root = tmp_path / "data" / "analytics"
    market_run = analytics_root / "market_temperature" / "runs" / "as_of=2026-08-14" / "run_market"
    industry_run = (
        analytics_root / "industry_structure" / "runs" / "as_of=2026-08-14" / "run_industry"
    )
    market_run.mkdir(parents=True)
    industry_run.mkdir(parents=True)

    _write_json(
        market_run / "manifest.json",
        {"as_of_date": "2026-08-14", "run_id": "run_market"},
    )
    _write_json(
        market_run / "scores.json",
        {
            "as_of_date": "2026-08-14",
            "composite": {"temperature": 55.0},
            "systemic_risk": {"level": "中等", "status": "moderate_systemic_risk"},
            "drivers": {
                "status": "ok",
                "comparison_as_of": "2026-08-13",
                "composite_delta": 3.0,
            },
            "dimensions": [
                {"dimension_id": "technical", "temperature": 62.0},
                {"dimension_id": "fund_flow", "temperature": 45.0},
                {"dimension_id": "valuation", "temperature": 55.0},
                {"dimension_id": "sentiment", "temperature": 52.0},
            ],
        },
    )
    pl.DataFrame(
        {
            "category": ["metric_value"] * 2,
            "dimension": ["sentiment", "fund_flow"],
            "metric_id": ["amount_top_5pct_share", "margin_balance_growth_20d"],
            "value_float": [0.32, -0.01],
            "metric_date": [as_of_date] * 2,
            "as_of_date": [as_of_date] * 2,
            "sample_size": [100, 1],
            "status": ["ok"] * 2,
        }
    ).write_parquet(market_run / "facts.parquet")

    _write_json(
        industry_run / "manifest.json",
        {"as_of_date": "2026-08-14", "run_id": "run_industry"},
    )
    _write_json(
        industry_run / "scores.json",
        {
            "structure_health": {
                "crowded_industry_share": 10.0,
                "positive_return_20d_count": 15,
                "positive_return_60d_count": 8,
                "scored_industry_count": 31,
            },
            "trend_diagnostics": {
                "positive_return_20d_count": 15,
                "positive_return_60d_count": 8,
                "scored_industry_count": 31,
            },
        },
    )
    pl.DataFrame(
        [
            {
                "industry_code": "801950",
                "industry_name": "煤炭",
                "status": "ok",
                "structure_score": 72.0,
                "structure_rank": 1,
                "momentum_score": 75.0,
                "valuation_score": 70.0,
                "fundamental_score": 65.0,
                "fund_flow_score": 80.0,
                "money_net_inflow_share_20d": 0.2,
                "return_20d": 0.1,
                "return_60d": 0.2,
                "crowding_temperature": 40.0,
                "tcr": 3.0,
                "tags": "资金确认",
            }
        ]
    ).write_parquet(industry_run / "industry_panel.parquet")

    result = run_quant_brief(
        target_date=as_of_date,
        output_root=analytics_root / "quant_brief",
    )

    nature = result.brief_json["nature"]
    assert nature["comparison_status"] == "available"
    assert nature["comparison_as_of"] == "2026-08-13"
    assert nature["composite_delta"] == 3.0
    assert result.manifest["comparison"]["previous_as_of_date"] == "2026-08-13"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
