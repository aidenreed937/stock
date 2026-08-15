"""Backfill CLI 单元测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from stock.cli.backfill import _execute_planned_tasks, main
from stock.data.planner import BackfillTask


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


def test_execute_planned_tasks_enables_batch_on_backfiller_pipeline() -> None:
    class BatchTarget:
        def __init__(self) -> None:
            self.enabled = 0
            self.committed = 0

        def enable_batch_mode(self) -> None:
            self.enabled += 1

        def commit(self) -> None:
            self.committed += 1

    store = BatchTarget()
    raw_store = BatchTarget()

    class Pipeline:
        def __init__(self) -> None:
            self.store = store
            self.raw_store = raw_store

    class Backfiller:
        def __init__(self, **_kwargs: object) -> None:
            self.pipeline = Pipeline()

        def backfill_range(
            self,
            start_date: date,
            end_date: date,
            *,
            force_refresh: bool = False,
            max_workers: int = 1,
        ) -> dict[str, int]:
            assert store.enabled == 1
            assert raw_store.enabled == 1
            assert force_refresh is True
            assert max_workers == 2
            return {
                "total_days": (end_date - start_date).days + 1,
                "open_days": 1,
                "synced_days": 1,
                "skipped_days": 0,
                "failed_days": 0,
            }

    task = BackfillTask(
        data_source="tushare",
        endpoint="daily_basic",
        symbol="",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 10),
        fetch_mode="per_day",
        is_single_sync=False,
    )

    with patch("stock.data.backfill.HistoricalBackfiller", Backfiller):
        summaries = _execute_planned_tasks([task], force_refresh=True, workers=2)

    assert store.committed == 1
    assert raw_store.committed == 1
    assert summaries[0]["data_source"] == "tushare"
    assert summaries[0]["endpoint"] == "daily_basic"
    assert summaries[0]["symbol"] == "全市场"


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


def test_backfill_cli_exits_nonzero_on_failed_days() -> None:
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
        mock_cfg.return_value = MagicMock()
        mock_instance = MagicMock()
        mock_instance.backfill_range.return_value = {
            "total_days": 3,
            "open_days": 3,
            "synced_days": 2,
            "skipped_days": 0,
            "failed_days": 1,
        }
        mock_backfiller_cls.return_value = mock_instance

        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 1
