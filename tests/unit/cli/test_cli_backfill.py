from unittest.mock import MagicMock, patch

import pytest

from stock.cli.backfill import main


def test_cli_backfill_help(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["backfill", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_cli_backfill_single_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "backfill",
            "--source",
            "mock",
            "--endpoint",
            "stock_daily_bar",
            "--symbol",
            "TEST.SH",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
        ],
    )
    with patch("stock.data.backfill.HistoricalBackfiller") as mock_backfiller_cls:
        mock_instance = MagicMock()
        mock_instance.backfill_range.return_value = {
            "total_days": 2,
            "open_days": 2,
            "synced_days": 2,
            "skipped_days": 0,
            "failed_days": 0,
        }
        mock_backfiller_cls.return_value = mock_instance
        main()
        mock_instance.backfill_range.assert_called_once()
