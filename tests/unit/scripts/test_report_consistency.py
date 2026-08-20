"""报告一致性脚本测试。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import polars as pl
from scripts.report_consistency import ConsistencyValidator

if TYPE_CHECKING:
    from pathlib import Path


def test_report_consistency_passes_for_valid_artifacts(tmp_path: Path) -> None:
    analytics_root = tmp_path / "analytics"
    _write_market(analytics_root, "2026-08-14", "run_market")
    _write_industry(analytics_root, "2026-08-14", "run_industry")
    _write_brief(
        analytics_root / "investor_brief" / "runs" / "as_of=2026-08-14" / "run_brief",
        "run_market",
        "run_industry",
    )
    _write_quant(
        analytics_root / "quant_brief" / "runs" / "as_of=2026-08-14" / "run_quant",
        "run_market",
        "run_industry",
    )

    result = ConsistencyValidator(analytics_root).validate_dates(["2026-08-14"])

    assert result.status == "passed"
    assert result.errors == []
    assert result.warnings == []


def test_report_consistency_warns_for_legacy_missing_quant_brief(tmp_path: Path) -> None:
    analytics_root = tmp_path / "analytics"
    _write_market(analytics_root, "2026-08-14", "run_market")
    _write_industry(analytics_root, "2026-08-14", "run_industry")
    _write_brief(
        analytics_root / "investor_brief" / "runs" / "as_of=2026-08-14" / "run_brief",
        "run_market",
        "run_industry",
    )

    result = ConsistencyValidator(analytics_root).validate_dates(["2026-08-14"])

    assert result.status == "passed"
    assert result.errors == []
    assert any(
        issue.check == "legacy_compatibility" and issue.artifact == "quant_brief"
        for issue in result.warnings
    )


def test_report_consistency_fails_for_unsourced_brief_industry(tmp_path: Path) -> None:
    analytics_root = tmp_path / "analytics"
    _write_market(analytics_root, "2026-08-14", "run_market")
    _write_industry(analytics_root, "2026-08-14", "run_industry")
    _write_brief(
        analytics_root / "investor_brief" / "runs" / "as_of=2026-08-14" / "run_brief",
        "run_market",
        "run_industry",
        candidate_name="不存在行业",
    )

    result = ConsistencyValidator(analytics_root).validate_dates(["2026-08-14"])

    assert result.status == "failed"
    assert any(issue.check == "brief_industry_source" for issue in result.errors)


def _write_market(root: Path, as_of_date: str, run_id: str) -> None:
    run_dir = root / "market_temperature" / "runs" / f"as_of={as_of_date}" / run_id
    run_dir.mkdir(parents=True)
    manifest = {"as_of_date": as_of_date, "run_id": run_id}
    scores = {
        "composite": {"temperature": 62.96, "status": "ready"},
        "systemic_risk": {"level": "中等偏高"},
        "dimensions": [
            {"name": "估值面", "temperature": 81.23},
            {"name": "资金面", "temperature": 47.64},
        ],
    }
    report = "2026-08-14 62.96 中等偏高 估值面 81.23 资金面 47.64"
    _write_common_json_and_reports(run_dir, manifest, scores, report)
    pl.DataFrame(
        {
            "category": ["data_watermark"] * 3,
            "dataset": ["stock_daily_bar", "margin", "moneyflow"],
            "metric_id": ["latest_trade_date"] * 3,
            "status": ["ok"] * 3,
            "value_text": [as_of_date] * 3,
        }
    ).write_parquet(run_dir / "facts.parquet")


def _write_industry(root: Path, as_of_date: str, run_id: str) -> None:
    run_dir = root / "industry_structure" / "runs" / f"as_of={as_of_date}" / run_id
    run_dir.mkdir(parents=True)
    manifest = {"as_of_date": as_of_date, "run_id": run_id}
    scores = {
        "structure_health": {"level": "修复中但偏脆弱"},
        "top_structure": [
            {"industry_name": "煤炭", "structure_score": 71.13},
            {"industry_name": "通信", "structure_score": 43.56},
        ],
        "lagging_or_weak": [{"industry_name": "通信"}],
    }
    report = "2026-08-14 修复中但偏脆弱 煤炭 71.13 通信 43.56"
    _write_common_json_and_reports(run_dir, manifest, scores, report)
    pl.DataFrame({"metric": ["x"]}).write_parquet(run_dir / "facts.parquet")
    pl.DataFrame(
        [
            {
                "industry_name": "煤炭",
                "structure_score": 71.13,
                "return_20d": 7.33,
                "return_60d": 5.52,
                "crowding_temperature": 30.89,
                "tags": "低估改善、相对占优",
            },
            {
                "industry_name": "通信",
                "structure_score": 43.56,
                "return_20d": 3.27,
                "return_60d": -3.88,
                "crowding_temperature": 87.80,
                "tags": "拥挤风险",
            },
        ]
    ).write_parquet(run_dir / "industry_panel.parquet")


def _write_brief(
    run_dir: Path,
    market_run_id: str,
    industry_run_id: str,
    *,
    candidate_name: str = "煤炭",
) -> None:
    run_dir.mkdir(parents=True)
    as_of_date = run_dir.parts[-2].split("=", maxsplit=1)[1]
    manifest = {
        "as_of_date": as_of_date,
        "run_id": run_dir.name,
        "inputs": {
            "market_temperature": {"as_of_date": as_of_date, "run_id": market_run_id},
            "industry_structure": {"as_of_date": as_of_date, "run_id": industry_run_id},
        },
    }
    brief_json = {
        "manifest": manifest,
        "participation": {"risk_level": "中等偏高"},
        "market_snapshot": {"composite_temperature": 62.96},
        "data_watermarks": {
            "stock_daily_bar": as_of_date,
            "margin": as_of_date,
            "moneyflow": as_of_date,
        },
        "industry_snapshot": {"structure_health": {"level": "修复中但偏脆弱"}},
        "candidate_industries": [
            {
                "industry_name": candidate_name,
                "structure_score": 71.13,
                "return_20d": 7.33,
                "return_60d": 5.52,
                "crowding_temperature": 30.89,
                "tags": "低估改善、相对占优",
            }
        ],
        "risk_industries": [
            {
                "industry_name": "通信",
                "structure_score": 43.56,
                "return_20d": 3.27,
                "return_60d": -3.88,
                "crowding_temperature": 87.80,
                "tags": "拥挤风险",
            }
        ],
        "lagging_industries": [
            {
                "industry_name": "通信",
                "structure_score": 43.56,
                "return_20d": 3.27,
                "return_60d": -3.88,
                "crowding_temperature": 87.80,
                "tags": "拥挤风险",
            }
        ],
    }
    markdown = (
        f"{as_of_date} {market_run_id} {industry_run_id} 62.96 中等偏高 "
        f"修复中但偏脆弱 {candidate_name} 通信 {as_of_date}"
    )
    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "brief_report.json", brief_json)
    (run_dir / "brief_report.md").write_text(markdown, encoding="utf-8")


def _write_quant(run_dir: Path, market_run_id: str, industry_run_id: str) -> None:
    run_dir.mkdir(parents=True)
    as_of_date = run_dir.parts[-2].split("=", maxsplit=1)[1]
    manifest = {
        "as_of_date": as_of_date,
        "run_id": run_dir.name,
        "inputs": {
            "market_temperature": {"as_of_date": as_of_date, "run_id": market_run_id},
            "industry_structure": {"as_of_date": as_of_date, "run_id": industry_run_id},
        },
    }
    brief_json = {
        "manifest": manifest,
        "macro": {"temperature": 62.96, "risk_level": "中等偏高"},
        "nature": {"composite_delta": None},
        "veto": {"top5pct": {"value": None}},
        "sector": {"priority": [], "avoid": [], "lagging": []},
    }
    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "brief_report.json", brief_json)
    (run_dir / "brief_report.md").write_text(as_of_date, encoding="utf-8")


def _write_common_json_and_reports(
    run_dir: Path,
    manifest: dict[str, object],
    scores: dict[str, object],
    report: str,
) -> None:
    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "scores.json", scores)
    _write_json(run_dir / "report.json", {"report": report})
    _write_json(run_dir / "quality_report.json", {"status": "ok"})
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    (run_dir / "human_report.md").write_text(report, encoding="utf-8")
    (run_dir / "quality_report.md").write_text("ok", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
