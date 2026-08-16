"""跨周期复盘脚本测试。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import polars as pl
from scripts.market_cycle_review import main

if TYPE_CHECKING:
    from pathlib import Path


def test_market_cycle_review_generates_payload_from_artifacts(tmp_path: Path) -> None:
    analytics_root = tmp_path / "analytics"
    output_root = tmp_path / "market_cycle_review"
    _write_day(
        analytics_root,
        {
            "date": "2026-08-13",
            "market_run": "run_market_1",
            "industry_run": "run_industry_1",
            "brief_run": "run_brief_1",
            "composite": 60.12,
            "fund_flow": 52.30,
            "technical": 45.20,
            "sentiment": 58.10,
            "risk": "中等",
            "health": "偏弱",
            "positive_20d": 12,
            "positive_60d": 2,
            "coal_tcr": 0.40,
        },
    )
    _write_day(
        analytics_root,
        {
            "date": "2026-08-14",
            "market_run": "run_market_2",
            "industry_run": "run_industry_2",
            "brief_run": "run_brief_2",
            "composite": 62.96,
            "fund_flow": 47.64,
            "technical": 67.39,
            "sentiment": 56.36,
            "risk": "中等偏高",
            "health": "修复中但偏脆弱",
            "positive_20d": 30,
            "positive_60d": 3,
            "coal_tcr": 0.52,
        },
    )

    result = main(
        [
            "--start",
            "2026-08-13",
            "--end",
            "2026-08-14",
            "--analytics-root",
            str(analytics_root),
            "--output-root",
            str(output_root),
        ]
    )

    assert result == 0
    payload = json.loads((output_root / "latest" / "review.json").read_text(encoding="utf-8"))
    markdown = (output_root / "latest" / "review.md").read_text(encoding="utf-8")
    assert payload["date_count"] == 2
    assert payload["market_summary"]["series"]["composite"]["end"] == 62.96
    assert payload["industry_frequency"]["brief_candidate_counts"][0] == {
        "industry_name": "煤炭",
        "days": 2,
    }
    assert "只读取已落盘市场温度、行业结构和投资者简报产物" in markdown
    assert any("区间起点" in reason for reason in payload["signal_days"][0]["reasons"])


def _write_day(root: Path, day: dict[str, Any]) -> None:
    _write_market(root, day)
    _write_industry(root, day)
    _write_brief(root, day)


def _write_market(root: Path, day: dict[str, Any]) -> None:
    as_of_date = str(day["date"])
    run_id = str(day["market_run"])
    run_dir = root / "market_temperature" / "runs" / f"as_of={as_of_date}" / run_id
    dimensions = [
        ("valuation", "估值面", 81.23),
        ("fund_flow", "资金面", day["fund_flow"]),
        ("sentiment", "情绪面", day["sentiment"]),
        ("technical", "技术面", day["technical"]),
        ("fundamental", "基本面", 60.70),
        ("macro_liquidity", "宏观流动性", 60.57),
    ]
    scores = {
        "composite": {"temperature": day["composite"], "status": "ready"},
        "systemic_risk": {"level": day["risk"]},
        "dimensions": [
            {"dimension_id": key, "name": name, "temperature": value}
            for key, name, value in dimensions
        ],
    }
    report = _report_text(
        as_of_date,
        str(day["risk"]),
        [(name, value) for _, name, value in dimensions],
        day["composite"],
    )
    _write_common_reports(run_dir, as_of_date, run_id, scores, report)
    pl.DataFrame(
        [
            {"metric_id": "advance_share", "value_float": 43.30},
            {"metric_id": "above_ma20_share", "value_float": 0.80},
            {"metric_id": "above_ma60_share", "value_float": 0.38},
            {"metric_id": "return_20d", "value_float": 7.20},
            {"metric_id": "margin_balance_growth_20d", "value_float": -0.06},
            {"metric_id": "main_money_net_inflow_share", "value_float": -0.05},
            {"metric_id": "market_amount_percentile_1250d", "value_float": 70.0},
            {"metric_id": "turnover_rate_percentile_1250d", "value_float": 65.0},
        ]
    ).write_parquet(run_dir / "facts.parquet")


def _write_industry(root: Path, day: dict[str, Any]) -> None:
    as_of_date = str(day["date"])
    run_id = str(day["industry_run"])
    run_dir = root / "industry_structure" / "runs" / f"as_of={as_of_date}" / run_id
    scores = {
        "structure_health": {
            "level": day["health"],
            "positive_return_20d_count": day["positive_20d"],
            "positive_return_60d_count": day["positive_60d"],
            "crowded_industry_count": 1,
            "strong_trend_count": 1,
        },
        "top_structure": [
            {"industry_name": "煤炭", "structure_score": 71.13},
            {"industry_name": "通信", "structure_score": 43.56},
        ],
        "lagging_or_weak": [{"industry_name": "通信"}],
    }
    report = f"{as_of_date} {day['health']} 煤炭 71.13 通信 43.56"
    _write_common_reports(run_dir, as_of_date, run_id, scores, report)
    pl.DataFrame({"metric": ["x"]}).write_parquet(run_dir / "facts.parquet")
    pl.DataFrame(
        [
            _industry_row(
                "煤炭",
                {
                    "structure_rank": 1,
                    "structure_score": 71.13,
                    "return_20d": 7.33,
                    "return_60d": 5.52,
                    "tcr": day["coal_tcr"],
                    "crowding_temperature": 30.89,
                    "tags": "低估改善",
                },
            ),
            _industry_row(
                "通信",
                {
                    "structure_rank": 31,
                    "structure_score": 43.56,
                    "return_20d": 3.27,
                    "return_60d": -3.88,
                    "tcr": 8.40,
                    "crowding_temperature": 87.80,
                    "tags": "拥挤风险",
                },
            ),
        ]
    ).write_parquet(run_dir / "industry_panel.parquet")


def _industry_row(name: str, values: dict[str, Any]) -> dict[str, Any]:
    return {"industry_name": name, **values}


def _write_brief(root: Path, day: dict[str, Any]) -> None:
    as_of_date = str(day["date"])
    run_id = str(day["brief_run"])
    run_dir = root / "investor_brief" / "runs" / f"as_of={as_of_date}" / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "as_of_date": as_of_date,
        "run_id": run_id,
        "inputs": {
            "market_temperature": {"as_of_date": as_of_date, "run_id": day["market_run"]},
            "industry_structure": {"as_of_date": as_of_date, "run_id": day["industry_run"]},
        },
    }
    candidate = _industry_row(
        "煤炭",
        {
            "structure_rank": 1,
            "structure_score": 71.13,
            "return_20d": 7.33,
            "return_60d": 5.52,
            "tcr": day["coal_tcr"],
            "crowding_temperature": 30.89,
            "tags": "低估改善",
        },
    )
    risk = _industry_row(
        "通信",
        {
            "structure_rank": 31,
            "structure_score": 43.56,
            "return_20d": 3.27,
            "return_60d": -3.88,
            "tcr": 8.40,
            "crowding_temperature": 87.80,
            "tags": "拥挤风险",
        },
    )
    brief_json = {
        "manifest": manifest,
        "participation": {"risk_level": day["risk"]},
        "market_snapshot": {"composite_temperature": day["composite"]},
        "industry_snapshot": {"structure_health": {"level": day["health"]}},
        "candidate_industries": [candidate],
        "risk_industries": [risk],
        "lagging_industries": [risk],
    }
    markdown = (
        f"{as_of_date} {day['market_run']} {day['industry_run']} {day['composite']} "
        f"{day['risk']} {day['health']} 煤炭 通信"
    )
    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "brief_report.json", brief_json)
    (run_dir / "brief_report.md").write_text(markdown, encoding="utf-8")


def _write_common_reports(
    run_dir: Path,
    as_of_date: str,
    run_id: str,
    scores: dict[str, Any],
    report: str,
) -> None:
    run_dir.mkdir(parents=True)
    _write_json(run_dir / "manifest.json", {"as_of_date": as_of_date, "run_id": run_id})
    _write_json(run_dir / "scores.json", scores)
    _write_json(run_dir / "report.json", {"report": report})
    _write_json(run_dir / "quality_report.json", {"status": "ok"})
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    (run_dir / "human_report.md").write_text(report, encoding="utf-8")
    (run_dir / "quality_report.md").write_text("ok", encoding="utf-8")


def _report_text(
    as_of_date: str,
    level: str,
    dimensions: list[tuple[str, object]],
    composite: object,
) -> str:
    dimension_text = " ".join(f"{name} {value}" for name, value in dimensions)
    return f"{as_of_date} {composite} {level} {dimension_text}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
