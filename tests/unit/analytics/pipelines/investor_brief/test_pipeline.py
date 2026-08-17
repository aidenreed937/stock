"""投资者简报管线测试。"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock.analytics.pipelines.investor_brief.pipeline import run_investor_brief
from stock.reporting.templates.investor_brief import _data_quality_notes

if TYPE_CHECKING:
    from pathlib import Path


def test_data_quality_notes_include_stale_metrics() -> None:
    manifest = {"as_of_date": "2026-08-14"}
    freshness = {
        "stale_metric_count": 1,
        "stale_metrics": [
            {
                "metric_id": "fs_profit_growth_temperature",
                "data_date": "2026-03-31",
                "dimension": "fundamental",
            }
        ],
    }

    notes = _data_quality_notes(manifest, freshness)

    stale_note = next(note for note in notes if "降权" in note)
    assert "fs_profit_growth_temperature" in stale_note
    assert "2026-03-31" in stale_note


def test_data_quality_notes_without_stale_keep_static() -> None:
    notes = _data_quality_notes({"as_of_date": "2026-08-14"}, {})

    assert len(notes) == 4
    assert not any("降权" in note for note in notes)


def test_run_investor_brief_writes_plain_language_report(tmp_path: Path) -> None:
    market_root = tmp_path / "market_temperature"
    industry_root = tmp_path / "industry_structure"
    output_root = tmp_path / "investor_brief"
    _write_market_artifacts(market_root)
    _write_industry_artifacts(industry_root)
    config_path = tmp_path / "investor_brief.yaml"
    config_path.write_text(
        f"""
investor_brief:
  schema_version: 1
  title: "测试投资者简报"
  artifact_root: "{output_root}"
  market_temperature_root: "{market_root}"
  industry_structure_root: "{industry_root}"
  max_candidate_industries: 3
  max_risk_industries: 3
  max_lagging_industries: 2
""",
        encoding="utf-8",
    )

    result = run_investor_brief(
        target_date=date(2026, 8, 14),
        config_path=config_path,
    )

    assert result.paths.brief_md.exists()
    assert (output_root / "latest" / "brief_report.md").exists()
    assert "## 1. 能不能参与" in result.brief_markdown
    assert "可以小心参与，但不是全面进攻环境" in result.brief_markdown
    assert "## 2. 短期配置观察" in result.brief_markdown
    assert "| 煤炭 |" in result.brief_markdown
    assert "| 环保 |" in result.brief_markdown
    assert "## 3. 不宜追高或需降温观察" in result.brief_markdown
    assert "| 通信 |" in result.brief_markdown
    assert "不构成个性化投资建议" in result.brief_markdown
    assert "fs_profit_growth_temperature" in result.brief_markdown
    assert "已超过新鲜度阈值" in result.brief_markdown
    assert result.brief_json["data_freshness"]["stale_metric_count"] == 1

    candidate_names = {row["industry_name"] for row in result.brief_json["candidate_industries"]}
    risk_names = {row["industry_name"] for row in result.brief_json["risk_industries"]}
    lagging_names = {row["industry_name"] for row in result.brief_json["lagging_industries"]}
    assert "煤炭" in candidate_names
    assert "综合" not in candidate_names
    assert "通信" not in candidate_names
    assert "通信" in risk_names
    assert "食品饮料" in lagging_names


def _write_market_artifacts(root: Path) -> None:
    run_dir = root / "runs" / "as_of=2026-08-14" / "run_market"
    run_dir.mkdir(parents=True)
    _write_json(run_dir / "manifest.json", {"as_of_date": "2026-08-14", "run_id": "run_market"})
    _write_json(
        run_dir / "scores.json",
        {
            "composite": {"temperature": 62.96, "status": "ready"},
            "systemic_risk": {
                "level": "中等偏高",
                "status": "elevated_systemic_risk",
                "message": "存在明确风险源，但尚未形成全面风险扩散。",
                "red_flags": ["估值面 81.23 已进入高温，安全边际收缩。"],
                "warnings": ["技术面偏热但资金面未同步确认。"],
                "offsets": ["宏观流动性 63.44 未构成主要压力。"],
            },
            "dimensions": [
                {"dimension_id": "valuation", "name": "估值面", "temperature": 81.23},
                {"dimension_id": "fund_flow", "name": "资金面", "temperature": 47.64},
                {"dimension_id": "technical", "name": "技术面", "temperature": 67.39},
            ],
            "data_freshness": {
                "stale_metric_count": 1,
                "stale_metrics": [
                    {
                        "metric_id": "fs_profit_growth_temperature",
                        "data_date": "2026-03-31",
                        "dimension": "fundamental",
                    }
                ],
            },
        },
    )


def _write_industry_artifacts(root: Path) -> None:
    run_dir = root / "runs" / "as_of=2026-08-14" / "run_industry"
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "manifest.json",
        {"as_of_date": "2026-08-14", "run_id": "run_industry"},
    )
    _write_json(
        run_dir / "scores.json",
        {
            "structure_health": {
                "status": "short_rebound_medium_unconfirmed",
                "level": "修复中但偏脆弱",
                "message": "短线行业扩散较强，但60日趋势和领先行业中期确认不足。",
                "scored_industry_count": 5,
                "positive_return_20d_count": 4,
                "positive_return_60d_count": 1,
            },
            "trend_diagnostics": {
                "status": "short_rebound_medium_unconfirmed",
                "message": "结构领先行业多数60日收益仍为负。",
            },
        },
    )
    pl.DataFrame(
        [
            _industry_row(
                "煤炭",
                structure_score=71.13,
                rank=1,
                return_20d=7.33,
                return_60d=5.52,
                crowding_temperature=30.89,
                tags="低估改善、相对占优",
            ),
            _industry_row(
                "环保",
                structure_score=68.04,
                rank=2,
                return_20d=9.67,
                return_60d=-9.77,
                crowding_temperature=25.20,
                tags="相对占优",
            ),
            _industry_row(
                "综合",
                structure_score=67.91,
                rank=3,
                return_20d=10.00,
                return_60d=-4.86,
                crowding_temperature=3.25,
                tags="强势主线、景气承压",
            ),
            _industry_row(
                "通信",
                structure_score=60.00,
                rank=4,
                return_20d=5.00,
                return_60d=-3.88,
                crowding_temperature=87.80,
                tags="拥挤风险",
            ),
            _industry_row(
                "食品饮料",
                structure_score=39.82,
                rank=5,
                return_20d=5.54,
                return_60d=-2.66,
                crowding_temperature=90.24,
                tags="拥挤风险、景气承压",
            ),
        ]
    ).write_parquet(run_dir / "industry_panel.parquet")


def _industry_row(name: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "industry_name": name,
        "industry_code": name,
        "status": "ok",
        "structure_score": 50.0,
        "structure_rank": 1,
        "momentum_score": 70.0,
        "valuation_score": 70.0,
        "fundamental_score": 60.0,
        "return_20d": 1.0,
        "return_60d": 1.0,
        "crowding_temperature": 50.0,
        "tcr": 1.0,
        "tags": "",
    }
    row.update(overrides)
    return row


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
