"""每日盘后复盘 CLI 单元测试。"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock_cli import daily_review


def test_daily_review_cli_parser() -> None:
    args = ["--as-of", "2026-08-21", "--output-dir", "output/test/"]
    p = daily_review.argparse.ArgumentParser()
    p.add_argument("--as-of", "-d", dest="as_of_date")
    p.add_argument("--output-dir", "-o", type=Path)
    parsed = p.parse_args(args)
    assert parsed.as_of_date == "2026-08-21"
    assert parsed.output_dir == Path("output/test/")


def test_daily_review_cli_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dummy_report_file = tmp_path / "dummy_report.md"
    dummy_report_file.write_text("# Dummy Report", encoding="utf-8")

    monkeypatch.setattr(
        daily_review,
        "generate_daily_review",
        MagicMock(return_value=dummy_report_file),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["stock_cli.daily_review", "--output-dir", str(tmp_path)],
    )

    daily_review.main()
