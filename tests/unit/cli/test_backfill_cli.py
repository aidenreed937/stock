"""Backfill CLI 单元测试。"""

from unittest.mock import MagicMock, patch

import pytest

from stock.cli.backfill import main


def test_backfill_cli_help() -> None:
    with patch("sys.argv", ["backfill.py", "--help"]), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_backfill_cli_basic_run() -> None:
    with (
        patch(
            "sys.argv",
            [
                "backfill.py",
                "--source",
                "tushare",
                "--endpoint",
                "daily_basic",
                "--start",
                "2026-08-10",
                "--end",
                "2026-08-12",
                "--max-workers",
                "1",
            ],
        ),
        patch("stock.cli.backfill.load_data_config") as mock_cfg,
        patch("stock.data.backfill.HistoricalBackfiller") as mock_backfiller_cls,
    ):
        mock_cfg.return_value = MagicMock(
            tushare=MagicMock(token="mock_token"),
            yfinance=MagicMock(),
            lixinger=MagicMock(token="mock_token"),
            fred=MagicMock(api_key="mock_key"),
        )
        mock_instance = MagicMock()
        mock_backfiller_cls.return_value = mock_instance

        main()
        mock_instance.backfill_range.assert_called_once()


def test_backfill_cli_universe_resolution() -> None:
    with (
        patch(
            "sys.argv",
            [
                "backfill.py",
                "--source",
                "tushare",
                "--endpoint",
                "stock_daily_bar",
                "--symbol",
                "600519.SH",
                "--start",
                "2026-08-10",
                "--end",
                "2026-08-12",
            ],
        ),
        patch("stock.cli.backfill.load_data_config") as mock_cfg,
        patch("stock.data.backfill.HistoricalBackfiller") as mock_backfiller_cls,
    ):
        mock_cfg.return_value = MagicMock(
            tushare=MagicMock(token="mock_token"),
            yfinance=MagicMock(),
            lixinger=MagicMock(token="mock_token"),
            fred=MagicMock(api_key="mock_key"),
        )
        mock_instance = MagicMock()
        mock_backfiller_cls.return_value = mock_instance

        main()
        mock_instance.backfill_range.assert_called_once()
