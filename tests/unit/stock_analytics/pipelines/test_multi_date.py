"""多日期业务管线测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_analytics.pipelines import multi_date_runner as multi_date


def _summary(tmp_path: Path, target_date: date) -> multi_date.MultiDateArtifactSummary:
    return multi_date.MultiDateArtifactSummary(
        as_of_date=target_date,
        market_temperature_run_dir=tmp_path / "market",
        industry_structure_run_dir=tmp_path / "industry",
        investor_brief_run_dir=tmp_path / "brief",
        quant_brief_run_dir=tmp_path / "quant",
    )


def test_run_multi_date_orchestrates_generation_validation_and_publish(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dates = [date(2026, 8, 18), date(2026, 8, 19)]
    calls: list[str] = []
    summaries = tuple(_summary(tmp_path, value) for value in dates)

    def _run_generation(target_dates, **_kwargs):
        calls.append("generate")
        assert target_dates == dates
        return summaries

    monkeypatch.setattr(multi_date, "run_multi_date_artifacts", _run_generation)
    monkeypatch.setattr(
        multi_date,
        "_validate_dates",
        lambda *_args, **_kwargs: calls.append("validate") or "validated",
    )
    monkeypatch.setattr(
        multi_date,
        "_publish_summary",
        lambda *_args, **_kwargs: calls.append("publish") or "published",
    )
    monkeypatch.setattr(
        multi_date,
        "_validate_latest",
        lambda _root: calls.append("latest") or "latest validated",
    )

    result = multi_date.run_multi_date(
        dates=dates,
        analytics_root=tmp_path / "analytics",
        publish_date=dates[0],
        run_class="experiment",
    )

    assert calls == ["generate", "validate", "publish", "latest"]
    assert result.summaries == summaries
    assert result.messages == ("validated", "published", "latest validated")
    assert result.published is True
