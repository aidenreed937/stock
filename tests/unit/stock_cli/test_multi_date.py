"""多日期分析 CLI 测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from stock_analytics.pipelines.multi_date_runner import MultiDateRunResult
from stock_cli import multi_date


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
    run = MagicMock(
        return_value=MultiDateRunResult(
            summaries=(),
            messages=("已通过一致性校验", "已发布 latest", "已通过 latest 一致性校验"),
            published=True,
        )
    )
    monkeypatch.setattr(multi_date, "run_multi_date", run)

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
    run.assert_called_once_with(
        dates=dates,
        start=None,
        end=None,
        last_n=None,
        refresh_mart=False,
        mart_start=None,
        storage_dir=None,
        analytics_root=analytics_root,
        publish_date=dates[0],
        run_class="experiment",
        collect_metric_values=None,
        no_publish_latest=False,
        dry_run=False,
    )
