"""多日期分析 CLI 测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_analytics.pipelines.multi_date import MultiDateArtifactSummary
from stock_cli import multi_date


def _summary(tmp_path: Path, target_date: date) -> MultiDateArtifactSummary:
    return MultiDateArtifactSummary(
        as_of_date=target_date,
        market_temperature_run_dir=tmp_path / "market",
        industry_structure_run_dir=tmp_path / "industry",
        investor_brief_run_dir=tmp_path / "brief",
        quant_brief_run_dir=tmp_path / "quant",
    )


def test_multi_date_cli_dry_run(capsys) -> None:
    result = multi_date.main(
        [
            "--dates",
            "2026-08-18",
            "2026-08-19",
            "--run-class",
            "experiment",
            "--dry-run",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "计划处理 2 个交易日" in output
    assert "experiment" in output


def test_multi_date_cli_generates_validates_and_publishes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dates = [date(2026, 8, 18), date(2026, 8, 19)]
    calls: list[tuple[str, object]] = []

    def _run_generation(target_dates, **kwargs):
        calls.append(("generate", (target_dates, kwargs)))
        return tuple(_summary(tmp_path, value) for value in target_dates)

    def _validate_dates(target_dates, **kwargs):
        calls.append(("validate", (target_dates, kwargs)))

    def _publish(summary, **kwargs):
        calls.append(("publish", (summary.as_of_date, kwargs)))

    def _validate_latest(root):
        calls.append(("latest", root))

    monkeypatch.setattr(multi_date, "_run_generation", _run_generation)
    monkeypatch.setattr(multi_date, "_validate_dates", _validate_dates)
    monkeypatch.setattr(multi_date, "_publish_summary", _publish)
    monkeypatch.setattr(multi_date, "_validate_latest", _validate_latest)

    analytics_root = tmp_path / "analytics"
    result = multi_date.main(
        [
            "--dates",
            "2026-08-18",
            "2026-08-19",
            "--publish-date",
            "2026-08-18",
            "--analytics-root",
            str(analytics_root),
            "--run-class",
            "experiment",
        ]
    )

    assert result == 0
    assert [item[0] for item in calls] == ["generate", "validate", "publish", "latest"]
    assert calls[0][1][1]["analytics_root"] == analytics_root
    assert calls[0][1][1]["run_class"] == "experiment"
    assert calls[2][1][0] == dates[0]
    assert calls[3][1] == analytics_root
