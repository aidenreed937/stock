"""DailySyncEngine 与 Sync CLI 单元测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from stock.cli.sync import main as sync_cli_main
from stock.data.sync import DailySyncEngine, SyncTaskItem


def test_sniff_watermarks() -> None:
    engine = DailySyncEngine(data_source="tushare")
    with patch.object(
        engine.catalog,
        "latest_trade_dates",
        side_effect=lambda dataset, n=1: (
            [date(2026, 8, 12)] if dataset == "stock_daily_bar" else []
        ),
    ):
        watermarks = engine.sniff_watermarks(["stock_daily_bar", "daily_basic"])
        assert watermarks["stock_daily_bar"] == date(2026, 8, 12)
        assert watermarks["daily_basic"] is None


def test_build_sync_plan_skips_unready_and_uptodate() -> None:
    engine = DailySyncEngine(data_source="tushare")

    def mock_is_ready(endpoint, target_date, current_datetime=None, data_source="tushare"):
        return endpoint == "stock_daily_bar"

    with (
        patch.object(
            engine,
            "sniff_watermarks",
            return_value={"stock_daily_bar": date(2026, 8, 12), "daily_basic": date(2026, 8, 12)},
        ),
        patch(
            "stock.data.update_scheduler.DataUpdateScheduler.is_data_ready",
            side_effect=mock_is_ready,
        ),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 8, 13), endpoints=["stock_daily_bar", "daily_basic"]
        )

        bar_task = next(p for p in plan if p.endpoint == "stock_daily_bar")
        basic_task = next(p for p in plan if p.endpoint == "daily_basic")

        # stock_daily_bar 已就绪且水位为 8-12，目标 8-13 -> 应该为 PENDING
        assert bar_task.status == "PENDING"
        assert bar_task.start_date == date(2026, 8, 13)
        assert bar_task.end_date == date(2026, 8, 13)

        # daily_basic 窗口未就绪 -> 应该为 SKIPPED
        assert basic_task.status == "SKIPPED"
        assert not basic_task.is_ready


def test_build_sync_plan_uptodate() -> None:
    engine = DailySyncEngine(data_source="tushare")
    with (
        patch.object(
            engine,
            "sniff_watermarks",
            return_value={"stock_daily_bar": date(2026, 8, 13)},
        ),
        patch("stock.data.update_scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=date(2026, 8, 13), endpoints=["stock_daily_bar"])
        assert plan[0].status == "UP_TO_DATE"


def test_execute_plan_success_and_error() -> None:
    engine = DailySyncEngine(data_source="tushare", max_workers=2)

    plan = [
        SyncTaskItem(
            data_source="tushare",
            endpoint="stock_daily_bar",
            dataset="stock_daily_bar",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            watermark=date(2026, 8, 12),
            status="PENDING",
            is_ready=True,
        ),
        SyncTaskItem(
            data_source="tushare",
            endpoint="daily_basic",
            dataset="daily_basic",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            watermark=date(2026, 8, 12),
            status="PENDING",
            is_ready=True,
        ),
    ]

    mock_pipeline = MagicMock()
    mock_pipeline.sync_daily_bars.return_value = pl.DataFrame({"symbol": ["000001.SZ"]})

    def mock_create(data_source, endpoint):
        if endpoint == "daily_basic":
            raise RuntimeError("API Rate Limit")
        return mock_pipeline

    with patch("stock.data.sync.create_pipeline", side_effect=mock_create):
        results = engine.execute_plan(plan)
        assert len(results) == 2
        success = next(r for r in results if r.endpoint == "stock_daily_bar")
        failed = next(r for r in results if r.endpoint == "daily_basic")

        assert success.status == "SUCCESS"
        assert success.records == 1
        assert failed.status == "FAILED"
        assert "API Rate Limit" in str(failed.error)


def test_build_sync_plan_expands_per_symbol_with_symbol_watermark() -> None:
    class Watchlist:
        def __init__(self) -> None:
            self.indices = ["000001.SH", "399001.SZ"]
            self.funds: list[str] = []
            self.stocks: list[str] = []

        @staticmethod
        def get_base_date(symbol: str) -> date | None:
            return date(2010, 1, 1) if symbol == "399001.SZ" else None

    class Watchlists:
        tushare = Watchlist()

    class DataCfg:
        watchlists = Watchlists()

    engine = DailySyncEngine(data_source="tushare")

    def mock_load_dataset(dataset: str, symbols: list[str] | None = None, **kwargs):
        if symbols == ["000001.SH"]:
            return pl.DataFrame({"symbol": ["000001.SH"], "trade_date": [date(2026, 8, 12)]})
        return pl.DataFrame()

    with (
        patch("stock.data.sync.load_data_config", return_value=DataCfg()),
        patch.object(engine.catalog, "load_dataset", side_effect=mock_load_dataset),
        patch.object(engine, "sniff_watermarks", return_value={"index_daily_bar": None}),
        patch("stock.data.update_scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=date(2026, 8, 13), endpoints=["index_daily_bar"])

    assert [item.symbol for item in plan] == ["000001.SH", "399001.SZ"]
    assert all(item.status == "PENDING" for item in plan)
    assert plan[0].start_date == date(2026, 8, 13)
    assert plan[1].start_date == date(2010, 1, 1)


def test_execute_plan_passes_task_symbol_to_pipeline() -> None:
    engine = DailySyncEngine(data_source="tushare", max_workers=1)
    plan = [
        SyncTaskItem(
            data_source="tushare",
            endpoint="index_daily_bar",
            dataset="index_daily_bar",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            watermark=date(2026, 8, 12),
            status="PENDING",
            is_ready=True,
            symbol="000001.SH",
        )
    ]
    mock_pipeline = MagicMock()
    mock_pipeline.sync_daily_bars.return_value = pl.DataFrame({"symbol": ["000001.SH"]})

    with patch("stock.data.sync.create_pipeline", return_value=mock_pipeline):
        results = engine.execute_plan(plan)

    assert results[0].status == "SUCCESS"
    assert results[0].symbol == "000001.SH"
    mock_pipeline.sync_daily_bars.assert_called_once()
    assert mock_pipeline.sync_daily_bars.call_args.kwargs["symbol"] == "000001.SH"


def test_sync_daily_workflow_with_audit() -> None:
    engine = DailySyncEngine(data_source="tushare", max_workers=1)

    with (
        patch.object(engine, "build_sync_plan", return_value=[]),
        patch.object(engine, "execute_plan", return_value=[]),
        patch("stock.data.audit.reconciliation.run_audit", return_value={"integrity_rate": 100.0}),
    ):
        plan, results, audit_res = engine.sync_daily(
            target_date=date(2026, 8, 13), run_audit_gate=True
        )
        assert plan == []
        assert results == []
        assert audit_res is None  # 无成功任务时不触发对账


def test_sync_cli_main(capsys) -> None:
    mock_plan = [
        SyncTaskItem(
            data_source="tushare",
            endpoint="stock_daily_bar",
            dataset="stock_daily_bar",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            watermark=date(2026, 8, 12),
            status="PENDING",
            is_ready=True,
            reason="待增量",
        )
    ]
    mock_res = [
        MagicMock(
            endpoint="stock_daily_bar",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            records=5541,
            duration_s=0.8,
            status="SUCCESS",
        )
    ]
    mock_audit = {"integrity_rate": 100.0}

    with (
        patch("sys.argv", ["sync.py", "-s", "tushare", "-d", "2026-08-13"]),
        patch.object(DailySyncEngine, "sync_daily", return_value=(mock_plan, mock_res, mock_audit)),
        patch("stock.cli.sync.logger.info") as mock_log,
    ):
        sync_cli_main()
        assert mock_log.called


def test_sync_cli_treats_no_data_as_failure() -> None:
    mock_plan = [
        SyncTaskItem(
            data_source="fred",
            endpoint="macro_indicators",
            dataset="macro_indicators",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            watermark=None,
            status="PENDING",
            is_ready=True,
            symbol="CPIAUCSL",
        )
    ]
    mock_res = [
        MagicMock(
            endpoint="macro_indicators",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            records=0,
            duration_s=0.1,
            status="NO_DATA",
            symbol="CPIAUCSL",
        )
    ]

    with (
        patch("sys.argv", ["sync.py", "-s", "fred", "-d", "2026-08-13"]),
        patch.object(DailySyncEngine, "sync_daily", return_value=(mock_plan, mock_res, None)),
        pytest.raises(SystemExit) as exc,
    ):
        sync_cli_main()

    assert exc.value.code == 1
