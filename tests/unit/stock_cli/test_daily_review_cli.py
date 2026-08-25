"""每日盘后复盘 CLI 单元测试。"""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_cli import daily_review


def test_daily_review_cli_parser() -> None:
    args = ["--as-of", "2026-08-21", "--output-dir", "output/test/"]
    parsed = daily_review._build_parser().parse_args(args)
    assert parsed.as_of_date == date(2026, 8, 21)
    assert parsed.output_dir == Path("output/test/")


def test_daily_review_cli_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dummy_report_file = tmp_path / "dummy_report.md"
    dummy_report_file.write_text("# Dummy Report", encoding="utf-8")

    run = MagicMock(return_value=SimpleNamespace(report_path=dummy_report_file))
    monkeypatch.setattr(daily_review, "run_daily_review", run)
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.daily_review", "--output-dir", str(tmp_path)],
    )

    daily_review.main()

    run.assert_called_once_with(
        target_date=None,
        output_dir=tmp_path,
        storage_dir=None,
        refresh_upstream=False,
    )
