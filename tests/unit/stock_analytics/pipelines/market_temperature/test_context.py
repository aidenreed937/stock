"""市场分析上下文与历史索引测试。"""

from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

from stock_analytics.pipelines.market_temperature.context import MarketAnalysisContext
from stock_analytics.pipelines.market_temperature.history import (
    rebuild_history_index,
    update_history_index,
)


def test_market_context_reuses_snapshot_and_history_index(tmp_path: Path) -> None:
    for offset in range(7):
        as_of = date(2026, 8, 1) + timedelta(days=offset)
        _write_run(tmp_path, as_of, f"run_{offset}", float(20 + offset))

    rebuild_history_index(tmp_path)
    _publish_latest(tmp_path, date(2026, 8, 7), "run_6")

    context = MarketAnalysisContext.load_latest(tmp_path)
    result = context.query(("overview", "trend", "risk", "history-extremes"))

    assert result["as_of_date"] == "2026-08-07"
    assert result["current"]["composite"]["temperature"] == 26.0
    assert result["trend"]["d5"]["composite_delta"] == 5.0
    assert result["risk"]["level"] == "低到中等"
    assert result["history_extremes"]["history_low"]["composite_temperature"] == 20.0
    assert result["history_extremes"]["current_percentile"] == 100.0


def test_market_context_explains_historical_date(tmp_path: Path) -> None:
    first_date = date(2026, 8, 1)
    _write_run(tmp_path, first_date, "run_first", 20.0)
    _write_run(tmp_path, date(2026, 8, 2), "run_second", 30.0)
    _publish_latest(tmp_path, date(2026, 8, 2), "run_second")

    context = MarketAnalysisContext.load_latest(tmp_path)
    result = context.query(("explain-date",), compare_date=first_date)

    assert result["explain_date"]["target"]["as_of_date"] == "2026-08-01"
    assert result["explain_date"]["compare_to_current"]["composite_delta"] == -10.0


def _write_run(root: Path, as_of: date, run_id: str, temperature: float) -> None:
    run_dir = root / "runs" / f"as_of={as_of.isoformat()}" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "artifact_type": "market_temperature",
        "as_of_date": as_of.isoformat(),
        "run_id": run_id,
        "run_class": "official",
        "generated_at": f"{as_of.isoformat()}T18:00:00+08:00",
        "provenance": {},
        "inputs": {},
        "watermarks": {},
    }
    snapshot = {
        "schema_version": 1,
        "as_of_date": as_of.isoformat(),
        "run_id": run_id,
        "identity": {},
        "composite": {"temperature": temperature, "status": "ready"},
        "dimensions": [
            {
                "dimension_id": "sentiment",
                "temperature": temperature,
                "status": "ready",
            }
        ],
        "dimension_groups": {},
        "systemic_risk": {
            "level": "低到中等",
            "status": "contained_systemic_risk",
            "red_flags": [],
            "warnings": [],
            "offsets": [],
        },
        "data_quality": {"status": "ready"},
        "provenance": {},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (run_dir / "scores.json").write_text(json.dumps(snapshot), encoding="utf-8")
    update_history_index(root, manifest=manifest, snapshot=snapshot)


def _publish_latest(root: Path, as_of: date, run_id: str) -> None:
    source = root / "runs" / f"as_of={as_of.isoformat()}" / run_id
    latest = root / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "snapshot.json", "scores.json"):
        shutil.copy2(source / name, latest / name)
