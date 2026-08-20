"""DailySyncEngine 与 Sync CLI 单元测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from stock_cli.sync import main as sync_cli_main
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


def test_sync_engine_reads_source_specific_worker_configuration() -> None:
    class Concurrency:
        lixinger_max_workers = 2
        default_max_workers = 4

    class DataCfg:
        concurrency = Concurrency()

    with patch("stock_data.pipeline.sync.load_data_config", return_value=DataCfg()):
        engine = DailySyncEngine(data_source="lixinger")

    assert engine.max_workers == 2


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
            return_value=MagicMock(frequency="event"),
        ),
    ):
        assert _sniff_watermarks(catalog, "tushare", ["stock_basic"]) == {
            "stock_basic": date(2026, 8, 18)
        }

    catalog.latest_refresh_dates.assert_called_once_with(dataset="stock_basic", n=1)
    catalog.latest_trade_dates.assert_not_called()


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
        patch("stock_data.pipeline.sync._disabled_endpoints", return_value=set()),
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


@pytest.mark.parametrize("endpoint", ["income", "fina_indicator", "balancesheet", "cashflow"])
def test_sync_symbols_keeps_tushare_statements_as_one_all_market_task(endpoint: str) -> None:
    assert _sync_symbols_for_task("tushare", endpoint) == [""]


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
