"""DailySyncEngine 与 Sync CLI 单元测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from stock_cli.sync import main as sync_cli_main
from stock_data.pipeline.scheduler import DataUpdateScheduler
from stock_data.pipeline.sync import DailySyncEngine, SyncTaskItem, _sync_symbols_for_task


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
            "stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready",
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
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=date(2026, 8, 13), endpoints=["stock_daily_bar"])
        assert plan[0].status == "UP_TO_DATE"


def test_build_sync_plan_retries_previous_trading_day_for_default_margin_sync() -> None:
    engine = DailySyncEngine(data_source="tushare")
    friday = date(2026, 8, 14)

    with (
        patch.object(engine, "sniff_watermarks", return_value={"margin": date(2026, 8, 13)}),
        patch.object(
            DataUpdateScheduler,
            "get_latest_trading_date",
            return_value=friday,
        ) as latest_trading_date,
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 8, 15),
            endpoints=["margin"],
            target_date_is_explicit=False,
        )

    assert len(plan) == 1
    assert plan[0].status == "PENDING"
    assert plan[0].start_date == friday
    assert plan[0].end_date == friday
    latest_trading_date.assert_called_once_with(
        date(2026, 8, 15), data_source="tushare", strictly_before=True
    )


def test_default_sync_falls_back_to_ready_trading_day_for_history_gap() -> None:
    engine = DailySyncEngine(data_source="tushare")
    target = date(2026, 8, 18)
    previous = date(2026, 8, 17)

    with (
        patch.object(engine, "sniff_watermarks", return_value={"daily_basic": date(2026, 8, 14)}),
        patch.object(
            DataUpdateScheduler,
            "get_latest_trading_date",
            side_effect=lambda target_date, data_source, strictly_before=False: (
                previous if target_date == target and not strictly_before else None
            ),
        ),
        patch(
            "stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready",
            side_effect=lambda endpoint,
            target_date,
            current_datetime=None,
            data_source="tushare": (target_date == previous),
        ),
    ):
        plan = engine.build_sync_plan(
            target_date=target,
            endpoints=["daily_basic"],
            target_date_is_explicit=False,
        )

    assert len(plan) == 1
    assert plan[0].status == "PENDING"
    assert plan[0].start_date == date(2026, 8, 15)
    assert plan[0].end_date == previous
    assert plan[0].watermark == date(2026, 8, 14)


def test_default_sync_keeps_non_daily_endpoint_on_target_date() -> None:
    engine = DailySyncEngine(data_source="tushare")
    target = date(2026, 8, 18)

    with (
        patch.object(engine, "sniff_watermarks", return_value={"cn_cpi": date(2026, 7, 1)}),
        patch.object(DataUpdateScheduler, "get_latest_trading_date") as latest_trading_date,
        patch(
            "stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready",
            return_value=False,
        ),
    ):
        plan = engine.build_sync_plan(
            target_date=target,
            endpoints=["cn_cpi"],
            target_date_is_explicit=False,
        )

    assert len(plan) == 1
    assert plan[0].status == "SKIPPED"
    assert plan[0].start_date == target
    assert plan[0].end_date == target
    latest_trading_date.assert_not_called()


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

    with patch("stock_data.pipeline.sync.create_pipeline", side_effect=mock_create):
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
        patch("stock_data.pipeline.sync.load_data_config", return_value=DataCfg()),
        patch.object(engine.catalog, "load_dataset", side_effect=mock_load_dataset),
        patch.object(engine, "sniff_watermarks", return_value={"index_daily_bar": None}),
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=date(2026, 8, 13), endpoints=["index_daily_bar"])

    assert [item.symbol for item in plan] == ["000001.SH", "399001.SZ"]
    assert all(item.status == "PENDING" for item in plan)
    assert plan[0].start_date == date(2026, 8, 13)
    assert plan[1].start_date == date(2010, 1, 1)


def test_build_sync_plan_expands_task_bundle_into_atomic_tasks() -> None:
    engine = DailySyncEngine(data_source="lixinger")
    bundle_tasks = [
        "sw_2021_constituents",
        "sw_2021_fundamental",
        "sw_2021_l2_fundamental",
        "sw_2021_fs_non_financial",
        "sw_2021_fs_bank",
        "sw_2021_fs_security",
        "sw_2021_fs_insurance",
    ]

    with (
        patch.object(
            engine,
            "sniff_watermarks",
            return_value=dict.fromkeys(bundle_tasks),
        ) as sniff_watermarks,
        patch("stock_data.pipeline.sync._sync_symbols_for_task", return_value=[""]),
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=date(2026, 8, 13), endpoints=["industry_bundle"])

    assert [item.endpoint for item in plan] == bundle_tasks
    assert all(item.status == "PENDING" for item in plan)
    sniff_watermarks.assert_called_once_with(bundle_tasks)


def test_sync_symbols_keeps_lixinger_batch_tasks_single() -> None:
    class Watchlist:
        def __init__(self) -> None:
            self.stocks = ["600519.SH", "000001.SZ"]

    class Watchlists:
        lixinger = Watchlist()

    class DataCfg:
        watchlists = Watchlists()

    with patch("stock_data.pipeline.sync.load_data_config", return_value=DataCfg()):
        assert _sync_symbols_for_task("lixinger", "index_fundamental") == [""]
        assert _sync_symbols_for_task("lixinger", "sw_2021_fundamental") == [""]
        assert _sync_symbols_for_task("lixinger", "national_debt") == [""]
        assert _sync_symbols_for_task("lixinger", "company_fundamental") == [
            "600519.SH",
            "000001.SZ",
        ]


def test_sync_symbols_filters_lixinger_unsupported_index() -> None:
    class Watchlist:
        def __init__(self) -> None:
            self.indices = ["000001", "399102", "399001"]

    class Watchlists:
        def __init__(self) -> None:
            self.lixinger = Watchlist()

    class DataCfg:
        def __init__(self) -> None:
            self.watchlists = Watchlists()
            self.source_endpoint_supports = {"lixinger": {"index_daily_bar": ["000001", "399001"]}}

    with patch("stock_data.pipeline.sync.load_data_config", return_value=DataCfg()):
        assert _sync_symbols_for_task("lixinger", "index_daily_bar") == [
            "000001",
            "399001",
        ]


def test_build_sync_plan_filters_unsupported_tushare_index_dailybasic() -> None:
    supported = ["000001.SH", "399001.SZ", "000300.SH", "000905.SH", "399006.SZ"]
    unsupported = ["000852.SH", "000985.CSI", "000922.CSI", "399102.SZ", "000688.SH"]

    class Watchlist:
        def __init__(self) -> None:
            self.indices = supported + unsupported

    class Watchlists:
        def __init__(self) -> None:
            self.tushare = Watchlist()

    class DataCfg:
        def __init__(self) -> None:
            self.watchlists = Watchlists()
            self.source_endpoint_supports = {"tushare": {"index_dailybasic": supported}}

    engine = DailySyncEngine(data_source="tushare")
    with (
        patch("stock_data.pipeline.sync.load_data_config", return_value=DataCfg()),
        patch.object(engine, "sniff_watermarks", return_value={"index_dailybasic": None}),
        patch("stock_data.pipeline.sync._symbol_watermark", return_value=None),
        patch("stock_data.pipeline.sync.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=date(2026, 8, 14), endpoints=["index_dailybasic"])

    assert [item.symbol for item in plan] == supported
    assert not any(item.symbol in unsupported for item in plan)


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

    with patch("stock_data.pipeline.sync.create_pipeline", return_value=mock_pipeline):
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
        patch(
            "stock_data.governance.audit.reconciliation.run_audit",
            return_value={"integrity_rate": 100.0},
        ),
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
        patch("stock_cli.sync.logger.info") as mock_log,
    ):
        sync_cli_main()
        assert mock_log.called


def test_sync_cli_forwards_comma_separated_task_bundles() -> None:
    with (
        patch(
            "sys.argv",
            [
                "sync.py",
                "-s",
                "tushare",
                "-e",
                "daily_market_bundle,fund_daily_bundle,hsgt_flow_bundle",
            ],
        ),
        patch.object(DailySyncEngine, "sync_daily", return_value=([], [], None)) as sync_daily,
    ):
        sync_cli_main()

    assert sync_daily.call_args.kwargs["endpoints"] == [
        "daily_market_bundle",
        "fund_daily_bundle",
        "hsgt_flow_bundle",
    ]


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
