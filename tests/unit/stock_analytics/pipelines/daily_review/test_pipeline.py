"""每日复盘业务管线测试。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from stock_analytics.pipelines.daily_review import pipeline
from stock_analytics.pipelines.watchlist_scanner.types import WatchlistScanResult


def test_build_temperature_summary_uses_market_context() -> None:
    result = pipeline._build_temperature_summary(
        {
            "current": {
                "composite": {"temperature": 42.0},
                "dimensions": [{"dimension_id": "technical", "temperature": 45.0}],
            }
        }
    )

    assert result == (42.0, "冰点偏冷 (谨慎蓄势区)", {"technical": 45.0})


def test_run_daily_review_composes_and_persists_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    scan_result = WatchlistScanResult(as_of_date="2026-08-21", total_scanned=0, items=[])
    market_context = {
        "as_of_date": "2026-08-21",
        "run_id": "market_run",
        "current": {
            "composite": {"temperature": 42.0},
            "dimensions": [{"dimension_id": "technical", "temperature": 45.0}],
        },
        "provenance": {"source_cutoffs": {"external_market": "2026-08-20"}},
    }
    renderer = MagicMock()
    renderer.render.return_value = "# report\n"

    monkeypatch.setattr(pipeline, "run_watchlist_scanner", lambda **_: scan_result)
    monkeypatch.setattr(
        pipeline,
        "_resolve_market_context",
        lambda *_, **__: market_context,
    )
    monkeypatch.setattr(
        pipeline,
        "_resolve_industry_structure",
        lambda *_, **__: (
            [{"name": "银行", "score": "80.0", "tags": ""}],
            [],
            {"source": "cached"},
        ),
    )
    monkeypatch.setattr(
        pipeline.ReportRenderer,
        "get_instance",
        classmethod(lambda _cls: renderer),
    )

    result = pipeline.run_daily_review(
        target_date=date(2026, 8, 21),
        output_dir=tmp_path,
    )

    assert result.as_of_date == date(2026, 8, 21)
    assert result.report_path.read_text(encoding="utf-8") == "# report\n"
    persisted = json.loads(result.context_path.read_text(encoding="utf-8"))
    assert persisted["market_context"]["run_id"] == "market_run"
    assert persisted["top_industries"][0]["name"] == "银行"
