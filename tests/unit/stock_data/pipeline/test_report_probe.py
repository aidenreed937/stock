from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from stock_data.core.task_resolution import resolve_task
from stock_data.pipeline.report_probe import ReportProbeDecision, YFinanceFinancialProbeStore
from stock_data.pipeline.sync_helpers import next_increment_start
from stock_data.pipeline.sync_planner import build_sync_plan


def _no_data_result(endpoint: str = "balance_sheet") -> SimpleNamespace:
    return SimpleNamespace(
        data_source="yfinance",
        endpoint=endpoint,
        symbol="AMZN",
        end_date=date(2026, 6, 30),
        status="NO_DATA_SOURCE",
        records=0,
    )


def test_yfinance_financial_probe_cools_down_and_persists(tmp_path: Path) -> None:
    store = YFinanceFinancialProbeStore(tmp_path, interval_days=7)
    checked_at = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)

    assert store.decide("balance_sheet", "AMZN", date(2026, 6, 30), checked_at).due

    store.record_results([_no_data_result()], current_datetime=checked_at)

    within_cooldown = store.decide(
        "balance_sheet",
        "AMZN",
        date(2026, 6, 30),
        checked_at + timedelta(days=6, hours=23),
    )
    assert not within_cooldown.due
    assert within_cooldown.next_probe_at == checked_at + timedelta(days=7)
    assert store.path.is_file()

    after_cooldown = store.decide(
        "balance_sheet",
        "AMZN",
        date(2026, 6, 30),
        checked_at + timedelta(days=7),
    )
    assert after_cooldown.due


def test_yfinance_financial_probe_resets_when_new_report_arrives(tmp_path: Path) -> None:
    store = YFinanceFinancialProbeStore(tmp_path)
    checked_at = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    store.record_results([_no_data_result()], current_datetime=checked_at)

    assert store.decide("balance_sheet", "AMZN", date(2026, 9, 30), checked_at).due

    success = SimpleNamespace(
        data_source="yfinance",
        endpoint="balance_sheet",
        symbol="AMZN",
        end_date=date(2026, 9, 30),
        status="SUCCESS",
        records=1,
    )
    store.record_results(
        [success],
        latest_watermarks={("balance_sheet", "AMZN"): date(2026, 9, 30)},
        current_datetime=checked_at + timedelta(hours=1),
    )

    assert store.decide("balance_sheet", "AMZN", date(2026, 6, 30), checked_at).due
    current_period = store.decide(
        "balance_sheet", "AMZN", date(2026, 9, 30), checked_at + timedelta(hours=1)
    )
    assert not current_period.due


def test_yfinance_financial_probe_uses_epoch_for_missing_watermark(tmp_path: Path) -> None:
    store = YFinanceFinancialProbeStore(tmp_path)
    checked_at = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)

    result = _no_data_result()
    result.end_date = date(1970, 1, 1)
    store.record_results([result], current_datetime=checked_at)

    decision = store.decide(
        "balance_sheet", "AMZN", date(1970, 1, 1), checked_at + timedelta(days=1)
    )
    assert not decision.due


def test_yfinance_financial_plan_force_bypasses_probe_cooldown() -> None:
    endpoint = "balance_sheet"
    with patch(
        "stock_data.pipeline.sync_planner.DataUpdateScheduler.is_data_ready",
        return_value=True,
    ):
        plan = build_sync_plan(
            catalog=SimpleNamespace(),
            data_source="yfinance",
            target_date=date(2026, 9, 2),
            endpoints=[endpoint],
            force=True,
            current_datetime=None,
            target_date_is_explicit=False,
            sniff_watermarks=lambda _endpoints: {endpoint: date(2026, 6, 30)},
            disabled_endpoints=lambda _source: set(),
            sync_symbols_for_task=lambda _source, _endpoint: ["AMZN"],
            symbol_watermarks=lambda _catalog, _source, _dataset, _symbols: {
                "AMZN": date(2026, 6, 30)
            },
            symbol_refresh_watermarks=lambda _catalog, _source, _dataset, _symbols: {},
            schedule_endpoint=lambda _source, name, _symbol: name,
            next_increment_start=next_increment_start,
            symbol_base_date=lambda _source, _symbol, _endpoint: None,
            report_probe_decision=lambda *_args: ReportProbeDecision(due=False),
        )

    assert len(plan) == 1
    assert plan[0].status == "PENDING"
    assert plan[0].start_date == date(2026, 6, 30)
    assert plan[0].end_date == date(2026, 6, 30)


def test_yfinance_financial_plan_uses_report_period_and_cooldown() -> None:
    endpoint = "balance_sheet"
    with patch(
        "stock_data.pipeline.sync_planner.DataUpdateScheduler.is_data_ready",
        return_value=True,
    ):
        plan = build_sync_plan(
            catalog=SimpleNamespace(),
            data_source="yfinance",
            target_date=date(2026, 9, 2),
            endpoints=[endpoint],
            force=False,
            current_datetime=None,
            target_date_is_explicit=False,
            sniff_watermarks=lambda _endpoints: {endpoint: date(2026, 3, 31)},
            disabled_endpoints=lambda _source: set(),
            sync_symbols_for_task=lambda _source, _endpoint: ["AMZN"],
            symbol_watermarks=lambda _catalog, _source, _dataset, _symbols: {
                "AMZN": date(2026, 6, 30)
            },
            symbol_refresh_watermarks=lambda _catalog, _source, _dataset, _symbols: {},
            schedule_endpoint=lambda _source, name, _symbol: name,
            next_increment_start=next_increment_start,
            symbol_base_date=lambda _source, _symbol, _endpoint: None,
            report_probe_decision=lambda _endpoint, _symbol, report_period, _current: (
                ReportProbeDecision(
                    due=False,
                    next_probe_at=datetime(2026, 9, 9, 0, 0, tzinfo=UTC),
                )
                if report_period == date(2026, 6, 30)
                else ReportProbeDecision(due=True)
            ),
        )

    assert len(plan) == 1
    assert plan[0].status == "SKIPPED"
    assert plan[0].start_date == date(2026, 6, 30)
    assert plan[0].end_date == date(2026, 6, 30)
    assert "冷却至" in plan[0].reason


def test_yfinance_financial_plan_uses_each_symbols_local_report_watermark() -> None:
    endpoint = "balance_sheet"
    with patch(
        "stock_data.pipeline.sync_planner.DataUpdateScheduler.is_data_ready",
        return_value=True,
    ):
        plan = build_sync_plan(
            catalog=SimpleNamespace(),
            data_source="yfinance",
            target_date=date(2026, 9, 2),
            endpoints=[endpoint],
            force=False,
            current_datetime=None,
            target_date_is_explicit=False,
            sniff_watermarks=lambda _endpoints: {endpoint: date(2026, 3, 31)},
            disabled_endpoints=lambda _source: set(),
            sync_symbols_for_task=lambda _source, _endpoint: ["AMZN"],
            symbol_watermarks=lambda _catalog, _source, _dataset, _symbols: {
                "AMZN": date(2026, 3, 31)
            },
            symbol_refresh_watermarks=lambda _catalog, _source, _dataset, _symbols: {},
            schedule_endpoint=lambda _source, name, _symbol: name,
            next_increment_start=next_increment_start,
            symbol_base_date=lambda _source, _symbol, _endpoint: None,
            report_probe_decision=lambda _endpoint, _symbol, _report_period, _current: (
                ReportProbeDecision(due=True)
            ),
        )

    assert len(plan) == 1
    assert plan[0].status == "PENDING"
    assert plan[0].start_date == date(2026, 3, 31)
    assert plan[0].end_date == date(2026, 3, 31)


def test_yfinance_financial_plan_probes_current_report_watermark() -> None:
    endpoint = "balance_sheet"
    with patch(
        "stock_data.pipeline.sync_planner.DataUpdateScheduler.is_data_ready",
        return_value=True,
    ):
        plan = build_sync_plan(
            catalog=SimpleNamespace(),
            data_source="yfinance",
            target_date=date(2026, 9, 2),
            endpoints=[endpoint],
            force=False,
            current_datetime=None,
            target_date_is_explicit=False,
            sniff_watermarks=lambda _endpoints: {endpoint: date(2026, 6, 30)},
            disabled_endpoints=lambda _source: set(),
            sync_symbols_for_task=lambda _source, _endpoint: ["AMZN"],
            symbol_watermarks=lambda _catalog, _source, _dataset, _symbols: {
                "AMZN": date(2026, 6, 30)
            },
            symbol_refresh_watermarks=lambda _catalog, _source, _dataset, _symbols: {},
            schedule_endpoint=lambda _source, name, _symbol: name,
            next_increment_start=next_increment_start,
            symbol_base_date=lambda _source, _symbol, _endpoint: None,
            report_probe_decision=lambda _endpoint, _symbol, _report_period, _current: (
                ReportProbeDecision(due=True)
            ),
        )

    assert len(plan) == 1
    assert plan[0].status == "PENDING"
    assert plan[0].start_date == date(2026, 6, 30)
    assert plan[0].end_date == date(2026, 6, 30)
    assert plan[0].refresh_raw_cache


def test_yfinance_financial_tasks_are_report_period_tasks() -> None:
    for endpoint in ("financials", "balance_sheet", "cashflow"):
        task = resolve_task("yfinance", endpoint)
        assert task.frequency == "quarterly"
        assert task.query_mode == "period"
        assert task.fetch_mode == "per_symbol"
