"""市场跨周期复盘 CLI 单元测试。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_cli import market_cycle_review


def test_market_cycle_review_cli_delegates_to_pipeline(tmp_path: Path, monkeypatch) -> None:
    run = MagicMock(
        return_value=SimpleNamespace(
            dates=("2026-08-13", "2026-08-14"),
            paths={"json": tmp_path / "review.json", "markdown": tmp_path / "review.md"},
        )
    )
    monkeypatch.setattr(market_cycle_review, "run_market_cycle_review", run)

    result = market_cycle_review.main(
        [
            "--start",
            "2026-08-13",
            "--end",
            "2026-08-14",
            "--analytics-root",
            str(tmp_path / "analytics"),
            "--output-root",
            str(tmp_path / "output"),
            "--skip-consistency",
            "--no-latest",
        ]
    )

    assert result == 0
    run.assert_called_once_with(
        start="2026-08-13",
        end="2026-08-14",
        analytics_root=tmp_path / "analytics",
        output_root=tmp_path / "output",
        skip_consistency=True,
        update_latest=False,
    )
