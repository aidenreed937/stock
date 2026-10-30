"""DailySyncEngine 与 Sync CLI 单元测试。"""

from datetime import date, datetime
from threading import Lock
from time import sleep
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from stock_cli.sync import main as sync_cli_main
from stock_data.core.runtime import DataRuntimeContext
from stock_data.core.settings import DataSettings
from stock_data.pipeline.scheduler import DataUpdateScheduler
from stock_data.pipeline.sync import (
    DailySyncEngine,
    SyncExecutionResult,
    SyncTaskItem,
    _sniff_watermarks,
    _symbol_refresh_watermarks,
    _symbol_watermarks,
    _sync_symbols_for_task,
    _watermark_date_column,
)
from stock_data.pipeline.sync_helpers import (
    _semiconductor_inventory_complete_watermark,
    configured_source_workers,
)
from stock_data.pipeline.sync_runner import SYNC_SOURCES, SyncSourceRun, run_sync


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


def test_semiconductor_cowos_watermark_uses_published_date() -> None:
    assert _watermark_date_column("industry", "tsmc_cowos_capacity_estimates") == "published_date"


def test_semiconductor_cowos_snapshot_does_not_replay_without_force() -> None:
    engine = DailySyncEngine(data_source="industry")
    endpoint = "tsmc_cowos_capacity_estimates"
    with (
        patch.object(engine, "sniff_watermarks", return_value={endpoint: date(2026, 6, 15)}),
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 9, 13),
            endpoints=[endpoint],
            target_date_is_explicit=False,
        )

    assert len(plan) == 1
    assert plan[0].status == "UP_TO_DATE"
    assert "FORCE=1" in plan[0].reason


def test_semiconductor_cowos_snapshot_can_be_replayed_with_force() -> None:
    engine = DailySyncEngine(data_source="industry")
    endpoint = "tsmc_cowos_capacity_estimates"
    with (
        patch.object(engine, "sniff_watermarks", return_value={endpoint: date(2026, 6, 15)}),
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 9, 13),
            endpoints=[endpoint],
            force=True,
            target_date_is_explicit=False,
        )

    assert len(plan) == 1
    assert plan[0].status == "PENDING"


def test_semiconductor_inventory_watermark_requires_all_constituents() -> None:
    frame = pl.DataFrame(
        {
            "report_quarter": ["2026Q2"] * 7 + ["2026Q3"],
            "symbol": [
                "TXN",
                "ADI",
                "STM",
                "NXPI",
                "MU",
                "000660.KS",
                "005930.KS_DS",
                "ADI",
            ],
            "trade_date": [date(2026, 6, 30)] * 7 + [date(2026, 9, 30)],
        }
    )
    catalog = MagicMock()
    catalog.load_dataset.return_value = frame

    assert _semiconductor_inventory_complete_watermark(catalog) == date(2026, 6, 30)


def test_sync_engine_reads_source_specific_worker_configuration() -> None:
    class Concurrency:
        lixinger_max_workers = 2
        default_max_workers = 4

    class DataCfg:
        concurrency = Concurrency()

    with patch("stock_data.pipeline.sync.load_data_config", return_value=DataCfg()):
        engine = DailySyncEngine(data_source="lixinger")

    assert engine.max_workers == 2


def test_sync_reads_cross_source_worker_configuration() -> None:
    class Concurrency:
        source_max_workers = 3

    class DataCfg:
        concurrency = Concurrency()

    assert configured_source_workers(load_config=lambda: DataCfg()) == 3


def test_symbol_watermarks_support_report_and_statement_dates() -> None:
    class Catalog:
        @staticmethod
        def load_dataset(dataset: str, **kwargs):
            return pl.DataFrame(
                {
                    "symbol": ["AAPL", "MSFT"],
                    "asOfDate": ["2026-06-30", "20260630"],
                }
            )

    assert _symbol_watermarks(Catalog(), "yfinance", "financials", ["AAPL", "MSFT"]) == {
        "AAPL": date(2026, 6, 30),
        "MSFT": date(2026, 6, 30),
    }


@pytest.mark.parametrize("endpoint", ["income", "fina_indicator", "balancesheet", "cashflow"])
def test_tushare_statement_uses_report_period_without_symbol_watermark(
    endpoint: str,
) -> None:
    assert _sync_symbols_for_task("tushare", endpoint) == [""]
    assert _watermark_date_column("tushare", endpoint) == "end_date"


def test_sniff_watermarks_scans_shared_dataset_once() -> None:
    catalog = MagicMock()
    catalog.latest_trade_dates.return_value = [date(2026, 8, 18)]
    task = MagicMock(dataset="shared_dataset")

    with (
        patch(
            "stock_data.pipeline.sync.expand_task_targets",
            return_value=["endpoint_a", "endpoint_b"],
        ),
        patch("stock_data.pipeline.sync.resolve_task", return_value=task),
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value=set()),
    ):
        watermarks = _sniff_watermarks(catalog, "tushare", ["bundle"])

    assert watermarks == {"endpoint_a": date(2026, 8, 18), "endpoint_b": date(2026, 8, 18)}
    catalog.latest_trade_dates.assert_called_once_with(dataset="shared_dataset", n=1)


def test_sniff_watermarks_uses_fred_series_watermark_for_shared_dataset() -> None:
    catalog = MagicMock()
    catalog.load_dataset.return_value = pl.DataFrame(
        {"symbol": ["DEXCHUS"], "trade_date": [date(2026, 7, 31)]}
    )
    task = MagicMock(
        dataset="macro_indicators",
        api_name="DEXCHUS",
        fetch_mode="per_symbol",
    )

    with (
        patch(
            "stock_data.pipeline.sync.expand_task_targets",
            return_value=["DEXCHUS"],
        ),
        patch("stock_data.pipeline.sync.resolve_task", return_value=task),
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value=set()),
        patch("stock_data.pipeline.sync._watermark_date_column", return_value="trade_date"),
        patch(
            "stock_data.pipeline.sync.DataUpdateScheduler.get_endpoint_update_meta",
            return_value=MagicMock(frequency="daily"),
        ),
    ):
        watermarks = _sniff_watermarks(catalog, "fred", ["DEXCHUS"])

    assert watermarks == {"DEXCHUS": date(2026, 7, 31)}
    catalog.latest_trade_dates.assert_not_called()


def test_sniff_watermarks_uses_endpoint_period_column() -> None:
    catalog = MagicMock()
    catalog.latest_trade_dates.return_value = [date(2026, 11, 1)]

    with (
        patch(
            "stock_data.pipeline.sync.expand_task_targets",
            return_value=["cn_schedule"],
        ),
        patch(
            "stock_data.pipeline.sync.resolve_task",
            return_value=MagicMock(dataset="cn_schedule", api_name="cn_schedule"),
        ),
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value=set()),
        patch(
            "stock_data.pipeline.sync._watermark_date_column",
            return_value="month",
        ),
    ):
        assert _sniff_watermarks(catalog, "tushare", ["cn_schedule"]) == {
            "cn_schedule": date(2026, 11, 1)
        }

    catalog.latest_trade_dates.assert_called_once_with(
        dataset="cn_schedule", n=1, date_column="month"
    )


def test_sniff_watermarks_uses_refresh_date_for_static_endpoint() -> None:
    catalog = MagicMock()
    catalog.latest_refresh_dates.return_value = [date(2026, 8, 18)]
    task = MagicMock(dataset="stock_basic", api_name="stock_basic")

    with (
        patch(
            "stock_data.pipeline.sync.expand_task_targets",
            return_value=["stock_basic"],
        ),
        patch("stock_data.pipeline.sync.resolve_task", return_value=task),
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value=set()),
        patch(
            "stock_data.pipeline.sync.DataUpdateScheduler.get_endpoint_update_meta",
            return_value=MagicMock(frequency="static"),
        ),
    ):
        assert _sniff_watermarks(catalog, "tushare", ["stock_basic"]) == {
            "stock_basic": date(2026, 8, 18)
        }

    catalog.latest_refresh_dates.assert_called_once_with(dataset="stock_basic", n=1)
    catalog.latest_trade_dates.assert_not_called()


def test_sniff_watermarks_uses_business_date_for_event_endpoint() -> None:
    catalog = MagicMock()
    catalog.latest_trade_dates.return_value = [date(2026, 8, 25)]
    task = MagicMock(dataset="share_float", api_name="share_float")

    with (
        patch(
            "stock_data.pipeline.sync.expand_task_targets",
            return_value=["share_float"],
        ),
        patch("stock_data.pipeline.sync.resolve_task", return_value=task),
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value=set()),
        patch("stock_data.pipeline.sync._watermark_date_column", return_value="float_date"),
        patch(
            "stock_data.pipeline.sync.DataUpdateScheduler.get_endpoint_update_meta",
            return_value=MagicMock(frequency="event"),
        ),
    ):
        assert _sniff_watermarks(catalog, "tushare", ["share_float"]) == {
            "share_float": date(2026, 8, 25)
        }

    catalog.latest_trade_dates.assert_called_once_with(
        dataset="share_float", n=1, date_column="float_date"
    )
    catalog.latest_refresh_dates.assert_not_called()


def test_symbol_refresh_watermarks_reads_updated_at() -> None:
    class Catalog:
        @staticmethod
        def load_dataset(dataset: str, **kwargs):
            return pl.DataFrame(
                {
                    "symbol": ["AAPL", "MSFT"],
                    "updated_at": ["2026-08-18T08:00:00+00:00", "2026-08-17T08:00:00+00:00"],
                }
            )

    assert _symbol_refresh_watermarks(Catalog(), "yfinance", "dividends", ["AAPL", "MSFT"]) == {
        "AAPL": date(2026, 8, 18),
        "MSFT": date(2026, 8, 17),
    }


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


@pytest.mark.parametrize(
    ("endpoint", "lookback_days"),
    [
        ("stk_holdertrade", 31),
        ("repurchase", 31),
        ("block_trade", 5),
        ("share_float", 31),
    ],
)
def test_build_sync_plan_refreshes_event_window_after_watermark(
    endpoint: str, lookback_days: int
) -> None:
    engine = DailySyncEngine(data_source="tushare")
    target = date(2026, 9, 2)
    with (
        patch.object(engine, "sniff_watermarks", return_value={endpoint: target}),
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=target, endpoints=[endpoint])

    assert len(plan) == 1
    assert plan[0].status == "PENDING"
    assert plan[0].start_date == target
    assert plan[0].end_date == target
    assert plan[0].refresh_raw_cache is True


def test_build_sync_plan_refreshes_event_gap_with_capped_lookback() -> None:
    engine = DailySyncEngine(data_source="tushare")
    target = date(2026, 9, 2)
    watermark = date(2026, 8, 25)
    with (
        patch.object(engine, "sniff_watermarks", return_value={"repurchase": watermark}),
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=target, endpoints=["repurchase"])

    assert plan[0].start_date == watermark
    assert plan[0].end_date == target
    assert plan[0].refresh_raw_cache is True


def test_build_sync_plan_keeps_event_window_protection() -> None:
    engine = DailySyncEngine(data_source="tushare")
    target = date(2026, 9, 2)
    with (
        patch.object(engine, "sniff_watermarks", return_value={"share_float": target}),
        patch(
            "stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=False
        ),
    ):
        plan = engine.build_sync_plan(target_date=target, endpoints=["share_float"])

    assert plan[0].status == "SKIPPED"
    assert plan[0].refresh_raw_cache is False


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
            side_effect=lambda endpoint, target_date, current_datetime=None, data_source="tushare": (
                target_date == previous
            ),
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


def test_default_sync_targets_previous_complete_month() -> None:
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
    assert plan[0].start_date == date(2026, 7, 1)
    assert plan[0].end_date == date(2026, 7, 1)
    latest_trading_date.assert_not_called()


def test_monthly_increment_starts_at_next_month_period() -> None:
    engine = DailySyncEngine(data_source="tushare")
    with (
        patch.object(engine, "sniff_watermarks", return_value={"cn_cpi": date(2026, 6, 1)}),
        patch(
            "stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready",
            return_value=True,
        ),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 8, 18),
            endpoints=["cn_cpi"],
            target_date_is_explicit=False,
        )

    assert plan[0].status == "PENDING"
    assert plan[0].start_date == date(2026, 7, 1)
    assert plan[0].end_date == date(2026, 7, 1)


def test_monthly_date_watermark_is_compared_by_period() -> None:
    engine = DailySyncEngine(data_source="tushare")
    with (
        patch.object(engine, "sniff_watermarks", return_value={"shibor_lpr": date(2026, 7, 20)}),
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 8, 18),
            endpoints=["shibor_lpr"],
            target_date_is_explicit=False,
        )

    assert plan[0].status == "UP_TO_DATE"


@pytest.mark.parametrize("endpoint", ["income", "fina_indicator", "balancesheet", "cashflow"])
def test_financial_statement_sync_uses_quarter_end_all_market_task(endpoint: str) -> None:
    engine = DailySyncEngine(data_source="tushare")
    with (
        patch.object(engine, "sniff_watermarks", return_value={endpoint: date(2026, 3, 31)}),
        patch(
            "stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready",
            return_value=True,
        ),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 8, 20),
            endpoints=[endpoint],
            target_date_is_explicit=False,
        )

    assert len(plan) == 1
    assert plan[0].symbol == ""
    assert plan[0].status == "PENDING"
    assert plan[0].start_date == date(2026, 6, 30)
    assert plan[0].end_date == date(2026, 6, 30)


def test_financial_statement_sync_refreshes_current_report_period() -> None:
    engine = DailySyncEngine(data_source="tushare")
    with (
        patch.object(engine, "sniff_watermarks", return_value={"income": date(2026, 6, 30)}),
        patch(
            "stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready",
            return_value=True,
        ),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 8, 20),
            endpoints=["income"],
            target_date_is_explicit=False,
        )

    assert len(plan) == 1
    assert plan[0].status == "PENDING"
    assert plan[0].start_date == date(2026, 6, 30)
    assert plan[0].end_date == date(2026, 6, 30)
    assert "刷新报告期" in plan[0].reason
    assert plan[0].refresh_raw_cache is True


def test_industry_semi_equipment_skips_current_period_when_curated_covers_target() -> None:
    engine = DailySyncEngine(data_source="industry")
    with (
        patch.object(
            engine,
            "sniff_watermarks",
            return_value={"semiconductor_equipment_semi": date(2026, 3, 31)},
        ),
        patch(
            "stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready",
            return_value=True,
        ),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 6, 29),
            endpoints=["semiconductor_equipment_semi"],
            target_date_is_explicit=True,
        )

    assert len(plan) == 1
    assert plan[0].status == "UP_TO_DATE"
    assert plan[0].start_date == date(2026, 3, 31)
    assert plan[0].end_date == date(2026, 3, 31)
    assert plan[0].refresh_raw_cache is False


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


def test_execute_plan_distinguishes_expected_empty_from_source_empty() -> None:
    engine = DailySyncEngine(data_source="tushare", max_workers=1)
    empty_frame = pl.DataFrame()
    plan = [
        SyncTaskItem(
            data_source="tushare",
            endpoint="fund_adj",
            dataset="fund_adj",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            watermark=None,
            status="PENDING",
            is_ready=True,
            symbol="510300.SH",
        ),
        SyncTaskItem(
            data_source="tushare",
            endpoint="daily_basic",
            dataset="daily_basic",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            watermark=None,
            status="PENDING",
            is_ready=True,
        ),
    ]

    with patch(
        "stock_data.pipeline.sync.create_pipeline",
        return_value=MagicMock(sync_daily_bars=MagicMock(return_value=empty_frame)),
    ):
        results = engine.execute_plan(plan)

    expected = next(result for result in results if result.endpoint == "fund_adj")
    source_empty = next(result for result in results if result.endpoint == "daily_basic")
    assert expected.status == "NO_DATA_EXPECTED"
    assert source_empty.status == "NO_DATA_SOURCE"
    assert expected.error != source_empty.error


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


def test_build_sync_plan_uses_lixinger_quarter_end_for_financial_statements() -> None:
    endpoint = "sw_2021_fs_non_financial"
    engine = DailySyncEngine(data_source="lixinger")

    with (
        patch.object(engine, "sniff_watermarks", return_value={endpoint: date(2026, 3, 31)}),
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value=set()),
        patch(
            "stock_data.pipeline.sync.DataUpdateScheduler.is_data_ready",
            return_value=True,
        ),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 8, 13),
            endpoints=[endpoint],
            target_date_is_explicit=False,
        )

    assert len(plan) == 1
    assert plan[0].symbol == ""
    assert plan[0].watermark == date(2026, 3, 31)
    assert plan[0].start_date == date(2026, 6, 30)
    assert plan[0].end_date == date(2026, 6, 30)
    assert plan[0].status == "PENDING"


def test_build_sync_plan_expands_task_bundle_into_atomic_tasks() -> None:
    engine = DailySyncEngine(data_source="lixinger")
    bundle_tasks = [
        "sw_2021_constituents",
        "sw_2021_fundamental",
        "sw_2021_l2_fundamental",
    ]
    financial_bundle_tasks = [
        "sw_2021_fs_non_financial",
        "sw_2021_fs_bank",
        "sw_2021_fs_security",
        "sw_2021_fs_insurance",
        "sw_2021_l2_fs_non_financial",
        "sw_2021_l2_fs_bank",
        "sw_2021_l2_fs_security",
        "sw_2021_l2_fs_insurance",
        "sw_2021_l3_fs_non_financial",
        "sw_2021_l3_fs_bank",
        "sw_2021_l3_fs_security",
        "sw_2021_l3_fs_insurance",
    ]

    with (
        patch.object(
            engine, "sniff_watermarks", return_value=dict.fromkeys(bundle_tasks)
        ) as sniff_watermarks,
        patch("stock_data.pipeline.sync._sync_symbols_for_task", return_value=[""]),
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value=set()),
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=date(2026, 8, 13), endpoints=["industry_bundle"])

    assert [item.endpoint for item in plan] == bundle_tasks
    assert all(item.status == "PENDING" for item in plan)
    sniff_watermarks.assert_called_once_with(bundle_tasks)

    with (
        patch.object(
            engine,
            "sniff_watermarks",
            return_value=dict.fromkeys(financial_bundle_tasks),
        ) as sniff_watermarks,
        patch("stock_data.pipeline.sync._sync_symbols_for_task", return_value=[""]),
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value=set()),
        patch("stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        financial_plan = engine.build_sync_plan(
            target_date=date(2026, 8, 13),
            endpoints=["industry_financial_bundle"],
        )

    assert [item.endpoint for item in financial_plan] == financial_bundle_tasks
    assert all(item.status == "PENDING" for item in financial_plan)
    sniff_watermarks.assert_called_once_with(financial_bundle_tasks)


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
        assert _sync_symbols_for_task("lixinger", "sw_2021_fs_non_financial") == [""]
        assert _sync_symbols_for_task("lixinger", "national_debt") == [""]
        assert _sync_symbols_for_task("lixinger", "company_fundamental") == [
            "600519.SH",
            "000001.SZ",
        ]


@pytest.mark.parametrize("endpoint", ["regulatory_measures", "exchange_inquiry"])
def test_sync_symbols_limits_lixinger_risk_events_to_watchlist(endpoint: str) -> None:
    class Watchlist:
        stocks = ["600519", "000001"]

    class Watchlists:
        lixinger = Watchlist()

    class DataCfg:
        watchlists = Watchlists()

    with patch("stock_data.pipeline.sync.load_data_config", return_value=DataCfg()):
        assert _sync_symbols_for_task("lixinger", endpoint) == ["600519", "000001"]


@pytest.mark.parametrize("endpoint", ["income", "fina_indicator", "balancesheet", "cashflow"])
def test_sync_symbols_keeps_tushare_statements_as_one_all_market_task(endpoint: str) -> None:
    assert _sync_symbols_for_task("tushare", endpoint) == [""]


def test_sync_symbols_limits_tushare_fund_share_to_watchlist_funds() -> None:
    class Watchlist:
        funds = ["510300.SH", "588000.SH", "510050.SH"]

    class Watchlists:
        tushare = Watchlist()

    class DataCfg:
        watchlists = Watchlists()

    with (
        patch("stock_data.pipeline.sync.load_data_config", return_value=DataCfg()),
        patch("stock_data.pipeline.sync_helpers._load_curated_symbol_pool") as load_pool,
    ):
        assert _sync_symbols_for_task("tushare", "fund_share") == Watchlist.funds

    load_pool.assert_not_called()


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


def test_sync_symbols_isolates_each_fred_series_task() -> None:
    class Watchlist:
        macro_series = ["FEDFUNDS", "CPIAUCSL", "GDP"]

    class Watchlists:
        fred = Watchlist()

    class DataCfg:
        watchlists = Watchlists()

    with patch("stock_data.pipeline.sync.load_data_config", return_value=DataCfg()):
        assert _sync_symbols_for_task("fred", "FEDFUNDS") == ["FEDFUNDS"]
        assert _sync_symbols_for_task("fred", "macro_indicators") == [
            "FEDFUNDS",
            "CPIAUCSL",
            "GDP",
        ]


def test_build_sync_plan_uses_series_frequency_for_fred() -> None:
    engine = DailySyncEngine(data_source="fred", max_workers=1)
    with (
        patch.object(engine, "sniff_watermarks", return_value={"macro_indicators": None}),
        patch(
            "stock_data.pipeline.sync._sync_symbols_for_task",
            return_value=["CPIAUCSL"],
        ),
        patch(
            "stock_data.pipeline.sync._symbol_watermarks",
            return_value={"CPIAUCSL": date(2026, 7, 1)},
        ),
        patch(
            "stock_data.pipeline.scheduler.DataUpdateScheduler.is_data_ready",
            return_value=True,
        ),
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 8, 18),
            endpoints=["macro_indicators"],
            target_date_is_explicit=False,
        )

    assert len(plan) == 1
    assert plan[0].status == "UP_TO_DATE"
    assert plan[0].end_date == date(2026, 7, 1)


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
        patch("stock_data.pipeline.sync._symbol_watermarks", return_value=dict.fromkeys(supported)),
        patch("stock_data.pipeline.sync.DataUpdateScheduler.is_data_ready", return_value=True),
    ):
        plan = engine.build_sync_plan(target_date=date(2026, 8, 14), endpoints=["index_dailybasic"])

    assert [item.symbol for item in plan] == supported
    assert not any(item.symbol in unsupported for item in plan)


def test_build_sync_plan_skips_disabled_endpoint() -> None:
    engine = DailySyncEngine(data_source="lixinger")

    with (
        patch.object(engine, "sniff_watermarks", return_value={"sw_2021_fundamental": None}),
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value={"sw_2021_fundamental"}),
        patch("stock_data.pipeline.sync._sync_symbols_for_task") as sync_symbols,
    ):
        plan = engine.build_sync_plan(
            target_date=date(2026, 8, 14), endpoints=["sw_2021_fundamental"]
        )

    assert len(plan) == 1
    assert plan[0].status == "SKIPPED"
    assert "权限或额度" in plan[0].reason
    sync_symbols.assert_not_called()


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


def test_execute_plan_bypasses_raw_cache_for_refresh_task() -> None:
    engine = DailySyncEngine(data_source="tushare", max_workers=1)
    task = SyncTaskItem(
        data_source="tushare",
        endpoint="share_float",
        dataset="share_float",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 9, 2),
        watermark=date(2026, 9, 2),
        status="PENDING",
        is_ready=True,
        refresh_raw_cache=True,
    )
    mock_pipeline = MagicMock()
    mock_pipeline.sync_daily_bars.return_value = pl.DataFrame({"symbol": ["600000.SH"]})

    with patch("stock_data.pipeline.sync.create_pipeline", return_value=mock_pipeline):
        results = engine.execute_plan([task])

    assert results[0].status == "SUCCESS"
    assert mock_pipeline.sync_daily_bars.call_args.kwargs["use_raw_cache"] is False
    assert mock_pipeline.sync_daily_bars.call_args.kwargs["force_refresh"] is True


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


def test_sync_daily_skips_a_share_audit_for_non_tushare_source() -> None:
    engine = DailySyncEngine(data_source="alphavantage", max_workers=1)
    result = SyncExecutionResult(
        data_source="alphavantage",
        endpoint="fx_daily",
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 17),
        records=1,
        duration_s=0.1,
        status="SUCCESS",
    )

    with (
        patch.object(engine, "build_sync_plan", return_value=[]),
        patch.object(engine, "execute_plan", return_value=[result]),
        patch("stock_data.governance.audit.reconciliation.run_audit") as run_audit,
    ):
        plan, results, audit_res = engine.sync_daily(
            target_date=date(2026, 8, 17), run_audit_gate=True
        )

    assert plan == []
    assert results == [result]
    assert audit_res is None
    run_audit.assert_not_called()


def test_sync_daily_runs_a_share_audit_after_tushare_stock_bar() -> None:
    engine = DailySyncEngine(data_source="tushare", max_workers=1)
    result = SyncExecutionResult(
        data_source="tushare",
        endpoint="stock_daily_bar",
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 17),
        records=1,
        duration_s=0.1,
        status="SUCCESS",
    )
    audit_result = {"integrity_rate": 100.0}

    with (
        patch.object(engine, "build_sync_plan", return_value=[]),
        patch.object(engine, "execute_plan", return_value=[result]),
        patch(
            "stock_data.governance.audit.reconciliation.run_audit",
            return_value=audit_result,
        ) as run_audit,
    ):
        _, _, audit_res = engine.sync_daily(target_date=date(2026, 8, 17), run_audit_gate=True)

    assert audit_res == audit_result
    run_audit.assert_called_once_with(
        target_date=date(2026, 8, 17), data_source="tushare", quiet=True
    )


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


def test_sync_cli_initializes_runtime_directories_before_sync(tmp_path) -> None:
    data_root = tmp_path / "data"
    settings = DataSettings(data_root=data_root, cache_dir=data_root / "cache")

    with (
        patch("sys.argv", ["sync.py", "-s", "industry"]),
        patch("stock_cli.sync.data_settings", settings),
        patch("stock_cli.sync.run_sync", return_value=[]) as run_sync,
    ):
        sync_cli_main()

    assert settings.runtime_context.data_root.is_dir()
    assert settings.runtime_context.raw_root.is_dir()
    assert settings.runtime_context.curated_root.is_dir()
    assert settings.runtime_context.cache_root.is_dir()
    assert run_sync.call_args.kwargs["runtime"].data_root == data_root


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


def test_run_sync_all_parallelizes_sources_and_preserves_order() -> None:
    active = 0
    max_active = 0
    completed: list[str] = []
    lock = Lock()

    class FakeEngine:
        def __init__(self, data_source: str, max_workers: int | None, runtime) -> None:
            self.data_source = data_source

        def sync_daily(self, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            sleep(0.02)
            with lock:
                active -= 1
                completed.append(self.data_source)
            return [], [], None

    with patch("stock_data.pipeline.sync_runner.DailySyncEngine", FakeEngine):
        runs = run_sync(source="all", target_date=date(2026, 8, 13))

    assert [run.source for run in runs] == list(SYNC_SOURCES)
    assert set(completed) == set(SYNC_SOURCES)
    assert "yfinance" not in SYNC_SOURCES
    assert max_active >= 2


def test_sync_cli_treats_no_data_as_warning() -> None:
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
            status="NO_DATA_SOURCE",
            symbol="CPIAUCSL",
        )
    ]

    with (
        patch("sys.argv", ["sync.py", "-s", "fred", "-d", "2026-08-13"]),
        patch.object(DailySyncEngine, "sync_daily", return_value=(mock_plan, mock_res, None)),
    ):
        sync_cli_main()


def test_sync_cli_exits_nonzero_for_failed_execution() -> None:
    mock_res = [
        MagicMock(
            endpoint="macro_indicators",
            start_date=date(2026, 8, 13),
            end_date=date(2026, 8, 13),
            records=0,
            duration_s=0.1,
            status="FAILED",
            error="FRED 请求失败",
            symbol="CPIAUCSL",
        )
    ]

    with (
        patch("sys.argv", ["sync.py", "-s", "fred", "-d", "2026-08-13"]),
        patch.object(DailySyncEngine, "sync_daily", return_value=([], mock_res, None)),
        pytest.raises(SystemExit) as exc_info,
    ):
        sync_cli_main()

    assert exc_info.value.code == 1


def test_sync_cli_renders_all_source_summaries_before_exit() -> None:
    day = date(2026, 8, 13)
    failed_run = SyncSourceRun(
        source="lixinger",
        plan=[],
        results=[
            SyncExecutionResult(
                data_source="lixinger",
                endpoint="sw_2021_fs_non_financial",
                start_date=day,
                end_date=day,
                records=0,
                duration_s=0.1,
                status="FAILED",
                error="API 权限不足",
            )
        ],
        audit_result=None,
    )
    successful_run = SyncSourceRun(
        source="fred",
        plan=[],
        results=[
            SyncExecutionResult(
                data_source="fred",
                endpoint="macro_indicators",
                start_date=day,
                end_date=day,
                records=1,
                duration_s=0.1,
                status="SUCCESS",
            )
        ],
        audit_result=None,
    )

    with (
        patch("sys.argv", ["sync.py", "-s", "all"]),
        patch("stock_cli.sync.run_sync", return_value=[failed_run, successful_run]),
        patch("stock_cli.sync.logger.info") as logger_info,
        pytest.raises(SystemExit) as exc_info,
    ):
        sync_cli_main()

    rendered = "\n".join(str(call.args[0]) for call in logger_info.call_args_list)
    assert "--- [LIXINGER]" in rendered
    assert "--- [FRED]" in rendered
    assert exc_info.value.code == 1


def test_industry_sync_watermarks_and_window_protection() -> None:
    """测试 industry 垂直产业指标的水位嗅探与发布时间窗口保护机制。"""
    engine = DailySyncEngine(data_source="industry")

    # 1. 水位嗅探测试
    with patch.object(
        engine.catalog,
        "latest_trade_dates",
        return_value=[date(2026, 7, 31)],
    ):
        watermarks = engine.sniff_watermarks(["construction_machinery"])
        assert watermarks["construction_machinery"] == date(2026, 7, 31)

    # 2. 时间窗口保护测试 (未到 T+8 发布窗口时自动跳过)
    plan_skipped = engine.build_sync_plan(
        target_date=date(2026, 8, 31),
        endpoints=["construction_machinery"],
        force=False,
        current_datetime=datetime(2026, 9, 7, 12, 0),
    )
    assert len(plan_skipped) == 1
    assert plan_skipped[0].status == "SKIPPED"
    assert "窗口未到" in (plan_skipped[0].reason or "")

    # 3. 强制同步测试 (force=True 时变为 PENDING)
    plan_force = engine.build_sync_plan(
        target_date=date(2026, 8, 31),
        endpoints=["construction_machinery"],
        force=True,
        current_datetime=datetime(2026, 9, 7, 12, 0),
    )
    assert len(plan_force) == 1
    assert plan_force[0].status == "PENDING"
    assert plan_force[0].is_ready is True


def test_industry_sync_execution() -> None:
    """测试 industry 增量任务执行与结果结构化生成。"""
    engine = DailySyncEngine(data_source="industry")
    task = SyncTaskItem(
        data_source="industry",
        endpoint="construction_machinery",
        dataset="construction_machinery",
        start_date=date(2026, 8, 31),
        end_date=date(2026, 8, 31),
        watermark=date(2026, 7, 31),
        status="PENDING",
        is_ready=True,
        symbol="",
    )
    with patch(
        "stock_data.fetcher.industry.pipeline.execute_single_industry_task",
        return_value=103,
    ):
        results = engine.execute_plan([task], force_refresh=True)

    assert len(results) == 1
    assert results[0].endpoint == "construction_machinery"
    assert results[0].records == 103
    assert results[0].status == "SUCCESS"


def test_industry_sync_execution_passes_runtime_context(tmp_path) -> None:
    runtime = DataRuntimeContext.from_root(tmp_path / "runtime")
    runtime.ensure_directories()
    engine = DailySyncEngine(data_source="industry", max_workers=1, runtime=runtime)
    task = SyncTaskItem(
        data_source="industry",
        endpoint="semiconductor_memory_benchmark",
        dataset="semiconductor_memory_benchmark",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        watermark=None,
        status="PENDING",
        is_ready=True,
    )

    with patch(
        "stock_data.fetcher.industry.pipeline.execute_single_industry_task",
        return_value=1,
    ) as execute:
        results = engine.execute_plan([task], force_refresh=True)

    assert results[0].status == "SUCCESS"
    assert execute.call_args.kwargs["runtime"] is runtime
    assert execute.call_args.kwargs["start_date"] == date(2026, 7, 1)
    assert execute.call_args.kwargs["end_date"] == date(2026, 7, 31)
    assert execute.call_args.kwargs["force_refresh"] is True


def test_sync_source_run_treats_blocked_result_as_failure() -> None:
    day = date(2026, 8, 31)
    result = SyncExecutionResult(
        data_source="industry",
        endpoint="pv_wafer_monthly",
        start_date=day,
        end_date=day,
        records=0,
        duration_s=0.0,
        status="BLOCKED",
    )

    run = SyncSourceRun(source="industry", plan=[], results=[result], audit_result=None)

    assert run.has_failure is True


def test_run_sync_rebuilds_versioned_members_after_metadata_success(tmp_path) -> None:
    runtime = DataRuntimeContext.from_root(tmp_path / "runtime")
    runtime.ensure_directories()
    day = date(2026, 8, 31)
    plan = [
        SyncTaskItem(
            data_source="tushare",
            endpoint=endpoint,
            dataset=endpoint,
            start_date=day,
            end_date=day,
            watermark=None,
            status="PENDING",
            is_ready=True,
        )
        for endpoint in ("index_classify", "index_member")
    ]
    results = [
        SyncExecutionResult(
            data_source="tushare",
            endpoint=endpoint,
            start_date=day,
            end_date=day,
            records=1,
            duration_s=0.1,
            status="SUCCESS",
        )
        for endpoint in ("index_classify", "index_member")
    ]

    with (
        patch.object(DailySyncEngine, "sync_daily", return_value=(plan, results, None)),
        patch(
            "stock_data.pipeline.derived_refresh.materialize_index_member_versioned",
            return_value=pl.DataFrame({"src": ["SW2021"]}),
        ) as materialize,
    ):
        runs = run_sync(source="tushare", target_date=day, runtime=runtime)

    materialize.assert_called_once_with(runtime=runtime)
    assert runs[0].results[-1].endpoint == "index_member_versioned"
    assert runs[0].results[-1].status == "SUCCESS"


def test_run_sync_does_not_rebuild_versioned_members_for_uptodate_metadata() -> None:
    day = date(2026, 8, 31)
    plan = [
        SyncTaskItem(
            data_source="tushare",
            endpoint=endpoint,
            dataset=endpoint,
            start_date=day,
            end_date=day,
            watermark=day,
            status="UP_TO_DATE",
            is_ready=True,
        )
        for endpoint in ("index_classify", "index_member")
    ]

    with (
        patch.object(DailySyncEngine, "sync_daily", return_value=(plan, [], None)),
        patch(
            "stock_data.pipeline.derived_refresh.materialize_index_member_versioned"
        ) as materialize,
    ):
        runs = run_sync(source="tushare", target_date=day)

    materialize.assert_not_called()
    assert runs[0].results == []


def test_run_sync_reports_derived_rebuild_failure() -> None:
    day = date(2026, 8, 31)
    plan = [
        SyncTaskItem(
            data_source="tushare",
            endpoint=endpoint,
            dataset=endpoint,
            start_date=day,
            end_date=day,
            watermark=None,
            status="PENDING",
            is_ready=True,
        )
        for endpoint in ("index_classify", "index_member")
    ]
    results = [
        SyncExecutionResult(
            data_source="tushare",
            endpoint=endpoint,
            start_date=day,
            end_date=day,
            records=1,
            duration_s=0.1,
            status="SUCCESS",
        )
        for endpoint in ("index_classify", "index_member")
    ]

    with (
        patch.object(DailySyncEngine, "sync_daily", return_value=(plan, results, None)),
        patch(
            "stock_data.pipeline.derived_refresh.materialize_index_member_versioned",
            side_effect=RuntimeError("测试失败"),
        ),
    ):
        runs = run_sync(source="tushare", target_date=day)

    assert runs[0].results[-1].endpoint == "index_member_versioned"
    assert runs[0].results[-1].status == "FAILED"
    assert runs[0].has_failure is True


def test_run_sync_blocks_derived_rebuild_when_metadata_sync_is_partial() -> None:
    day = date(2026, 8, 31)
    plan = [
        SyncTaskItem(
            data_source="tushare",
            endpoint=endpoint,
            dataset=endpoint,
            start_date=day,
            end_date=day,
            watermark=None,
            status="PENDING",
            is_ready=True,
        )
        for endpoint in ("index_classify", "index_member")
    ]
    results = [
        SyncExecutionResult(
            data_source="tushare",
            endpoint="index_classify",
            start_date=day,
            end_date=day,
            records=1,
            duration_s=0.1,
            status="SUCCESS",
        ),
        SyncExecutionResult(
            data_source="tushare",
            endpoint="index_member",
            start_date=day,
            end_date=day,
            records=0,
            duration_s=0.1,
            status="FAILED",
            error="源表失败",
        ),
    ]

    with (
        patch.object(DailySyncEngine, "sync_daily", return_value=(plan, results, None)),
        patch(
            "stock_data.pipeline.derived_refresh.materialize_index_member_versioned"
        ) as materialize,
    ):
        runs = run_sync(source="tushare", target_date=day)

    materialize.assert_not_called()
    assert runs[0].results[-1].endpoint == "index_member_versioned"
    assert runs[0].results[-1].status == "BLOCKED"
    assert runs[0].has_failure is True
