"""Backfill CLI 单元测试。"""

import threading
import time
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_cli.backfill import _execute_planned_tasks, _resolve_universe_symbols, main
from stock_data.pipeline.planner import BackfillTask


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
        patch("stock_cli.backfill.load_data_config") as mock_cfg,
        patch("stock_data.pipeline.backfill.HistoricalBackfiller") as mock_backfiller_cls,
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

    with patch("stock_data.pipeline.backfill.HistoricalBackfiller", Backfiller):
        summaries = _execute_planned_tasks([task], force_refresh=True, workers=2)

    assert store.committed == 1
    assert raw_store.committed == 1
    assert summaries[0]["data_source"] == "tushare"
    assert summaries[0]["endpoint"] == "daily_basic"
    assert summaries[0]["symbol"] == "全市场"


def test_execute_planned_tasks_reuses_pipeline_without_reordering_tasks() -> None:
    class BatchTarget:
        def __init__(self) -> None:
            self.enabled = 0
            self.committed = 0

        def enable_batch_mode(self) -> None:
            self.enabled += 1

        def commit(self) -> None:
            self.committed += 1

    class Pipeline:
        def __init__(self) -> None:
            self.store = BatchTarget()
            self.raw_store = BatchTarget()

    instances: list[object] = []

    class Backfiller:
        def __init__(self, **kwargs: object) -> None:
            self.symbol = str(kwargs.get("symbol") or "")
            self.pipeline = kwargs.get("pipeline") or Pipeline()
            self.fetcher = kwargs.get("fetcher") or object()
            instances.append(self)

        def backfill_range(
            self,
            start_date: date,
            end_date: date,
            *,
            force_refresh: bool = False,
            max_workers: int = 1,
        ) -> dict[str, int]:
            return {
                "total_days": (end_date - start_date).days + 1,
                "open_days": 1,
                "synced_days": 1,
                "skipped_days": 0,
                "failed_days": 0,
            }

    tasks = [
        BackfillTask(
            data_source="tushare",
            endpoint="stock_daily_bar",
            symbol="000001.SZ",
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 10),
            fetch_mode="per_symbol",
            is_single_sync=False,
        ),
        BackfillTask(
            data_source="tushare",
            endpoint="index_daily",
            symbol="000300.SH",
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 10),
            fetch_mode="per_symbol",
            is_single_sync=False,
        ),
        BackfillTask(
            data_source="tushare",
            endpoint="stock_daily_bar",
            symbol="000002.SZ",
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 10),
            fetch_mode="per_symbol",
            is_single_sync=False,
        ),
    ]

    with patch("stock_data.pipeline.backfill.HistoricalBackfiller", Backfiller):
        summaries = _execute_planned_tasks(tasks, force_refresh=False, workers=1)

    assert len(instances) == 3
    assert instances[0].pipeline is instances[2].pipeline
    assert instances[0].pipeline is not instances[1].pipeline
    assert instances[0].pipeline.store.enabled == 1
    assert instances[0].pipeline.raw_store.enabled == 1
    assert instances[0].pipeline.store.committed == 1
    assert instances[0].pipeline.raw_store.committed == 1
    assert instances[1].pipeline.store.enabled == 1
    assert instances[1].pipeline.raw_store.enabled == 1
    assert instances[1].pipeline.store.committed == 1
    assert instances[1].pipeline.raw_store.committed == 1
    assert [s["symbol"] for s in summaries] == ["000001.SZ", "000300.SH", "000002.SZ"]


def test_execute_planned_tasks_parallelizes_per_symbol_tasks_without_reordering() -> None:
    class BatchTarget:
        def __init__(self) -> None:
            self.committed = 0

        def enable_batch_mode(self) -> None:
            pass

        def commit(self) -> None:
            self.committed += 1

    class Pipeline:
        def __init__(self) -> None:
            self.store = BatchTarget()
            self.raw_store = BatchTarget()

    active = 0
    max_active = 0
    active_lock = threading.Lock()

    class Backfiller:
        def __init__(self, **kwargs: object) -> None:
            self.symbol = str(kwargs.get("symbol") or "")
            self.pipeline = kwargs.get("pipeline") or Pipeline()
            self.fetcher = kwargs.get("fetcher") or object()

        def backfill_range(
            self,
            start_date: date,
            end_date: date,
            *,
            force_refresh: bool = False,
            max_workers: int = 1,
        ) -> dict[str, int]:
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with active_lock:
                active -= 1
            return {
                "total_days": (end_date - start_date).days + 1,
                "open_days": 1,
                "synced_days": 1,
                "skipped_days": 0,
                "failed_days": 0,
            }

    tasks = [
        BackfillTask(
            data_source="tushare",
            endpoint="income",
            symbol=symbol,
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 10),
            fetch_mode="per_symbol",
            is_single_sync=False,
        )
        for symbol in ("000001.SZ", "000002.SZ")
    ]

    with patch("stock_data.pipeline.backfill.HistoricalBackfiller", Backfiller):
        summaries = _execute_planned_tasks(tasks, force_refresh=True, workers=2)

    assert max_active == 2
    assert [summary["symbol"] for summary in summaries] == ["000001.SZ", "000002.SZ"]


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
        patch("stock_cli.backfill.load_data_config") as mock_cfg,
        patch("stock_data.pipeline.backfill.HistoricalBackfiller") as mock_backfiller_cls,
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


def test_backfill_cli_nested_watchlist_universe_keeps_watchlist_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_dir = tmp_path / "config" / "universe"
    universe_dir.mkdir(parents=True)
    (universe_dir / "watchlist.yaml").write_text(
        """
universe:
  a_shares:
    stocks:
      - code: "600519.SH"
    indices:
      - code: "000300.SH"
  global:
    stocks:
      - code: "AAPL"
  macro:
    - "FEDFUNDS"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert _resolve_universe_symbols("watchlist") == "watchlist"


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
        patch("stock_cli.backfill.load_data_config") as mock_cfg,
        patch("stock_data.pipeline.backfill.HistoricalBackfiller") as mock_backfiller_cls,
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
