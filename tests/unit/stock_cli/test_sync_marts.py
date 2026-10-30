"""同步后定向刷新 Domain Mart 测试。"""

from datetime import date
from unittest.mock import MagicMock, call

from stock_cli import sync_marts
from stock_data.pipeline.sync import SyncExecutionResult, SyncTaskItem
from stock_data.pipeline.sync_runner import SyncSourceRun


def test_refresh_synced_marts_groups_event_results(monkeypatch) -> None:
    build = MagicMock()
    monkeypatch.setattr(sync_marts, "build_features", build)
    run = SyncSourceRun(
        source="tushare",
        plan=[],
        results=[
            SyncExecutionResult(
                data_source="tushare",
                endpoint="stk_holdertrade",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 9, 2),
                records=1,
                duration_s=0.1,
                status="SUCCESS",
            ),
            SyncExecutionResult(
                data_source="tushare",
                endpoint="share_float",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 9, 2),
                records=0,
                duration_s=0.1,
                status="NO_DATA_SOURCE",
            ),
        ],
        audit_result=None,
    )

    sync_marts.refresh_synced_marts([run], enabled=True)

    assert {item.kwargs["target"] for item in build.call_args_list} == {
        "corporate_actions_daily",
        "unlock_pressure_daily",
        "smart_money_daily",
    }
    for item in build.call_args_list:
        if item.kwargs["target"] in {"corporate_actions_daily", "unlock_pressure_daily"}:
            assert item.kwargs["refresh_marts"] is True
        else:
            assert "refresh_marts" not in item.kwargs


def test_refresh_synced_marts_skips_failed_event_group(monkeypatch) -> None:
    build = MagicMock()
    monkeypatch.setattr(sync_marts, "build_features", build)
    run = SyncSourceRun(
        source="tushare",
        plan=[],
        results=[
            SyncExecutionResult(
                data_source="tushare",
                endpoint="repurchase",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 9, 2),
                records=0,
                duration_s=0.1,
                status="FAILED",
            )
        ],
        audit_result=None,
    )

    sync_marts.refresh_synced_marts([run], enabled=True)

    build.assert_not_called()


def test_refresh_synced_marts_refreshes_smart_money_with_its_inputs(monkeypatch) -> None:
    build = MagicMock()
    monkeypatch.setattr(sync_marts, "build_features", build)
    run = SyncSourceRun(
        source="tushare",
        plan=[],
        results=[
            SyncExecutionResult(
                data_source="tushare",
                endpoint="stock_daily_bar",
                start_date=date(2026, 10, 9),
                end_date=date(2026, 10, 9),
                records=1,
                duration_s=0.1,
                status="SUCCESS",
            ),
            SyncExecutionResult(
                data_source="tushare",
                endpoint="stk_holdertrade",
                start_date=date(2026, 10, 9),
                end_date=date(2026, 10, 9),
                records=1,
                duration_s=0.1,
                status="SUCCESS",
            ),
            SyncExecutionResult(
                data_source="tushare",
                endpoint="block_trade",
                start_date=date(2026, 10, 9),
                end_date=date(2026, 10, 9),
                records=1,
                duration_s=0.1,
                status="SUCCESS",
            ),
        ],
        audit_result=None,
    )

    sync_marts.refresh_synced_marts([run], enabled=False)

    assert build.call_args_list == [
        call(
            target="corporate_actions_daily",
            start_date=date(2026, 10, 9),
            end_date=date(2026, 10, 9),
            refresh_marts=True,
        ),
        call(
            target="smart_money_daily",
            start_date=date(2026, 10, 9),
            end_date=date(2026, 10, 9),
        ),
    ]


def test_refresh_synced_marts_skips_smart_money_when_input_failed(monkeypatch) -> None:
    build = MagicMock()
    monkeypatch.setattr(sync_marts, "build_features", build)
    run = SyncSourceRun(
        source="tushare",
        plan=[],
        results=[
            SyncExecutionResult(
                data_source="tushare",
                endpoint="stock_daily_bar",
                start_date=date(2026, 10, 9),
                end_date=date(2026, 10, 9),
                records=1,
                duration_s=0.1,
                status="SUCCESS",
            ),
            SyncExecutionResult(
                data_source="tushare",
                endpoint="block_trade",
                start_date=date(2026, 10, 9),
                end_date=date(2026, 10, 9),
                records=0,
                duration_s=0.1,
                status="FAILED",
            ),
        ],
        audit_result=None,
    )

    sync_marts.refresh_synced_marts([run], enabled=False)

    build.assert_not_called()


def test_refresh_synced_marts_refreshes_iv_after_source_updates(monkeypatch) -> None:
    build = MagicMock()
    monkeypatch.setattr(sync_marts, "build_features", build)
    tushare_run = SyncSourceRun(
        source="tushare",
        plan=[],
        results=[
            SyncExecutionResult(
                data_source="tushare",
                endpoint="opt_daily",
                start_date=date(2026, 10, 9),
                end_date=date(2026, 10, 9),
                records=100,
                duration_s=0.1,
                status="SUCCESS",
            )
        ],
        audit_result=None,
    )
    lixinger_run = SyncSourceRun(
        source="lixinger",
        plan=[],
        results=[
            SyncExecutionResult(
                data_source="lixinger",
                endpoint="national_debt",
                start_date=date(2026, 10, 9),
                end_date=date(2026, 10, 9),
                records=1,
                duration_s=0.1,
                status="SUCCESS",
            )
        ],
        audit_result=None,
    )

    sync_marts.refresh_synced_marts([tushare_run, lixinger_run], enabled=False)

    build.assert_called_once_with(
        target="settlement_iv_proxy_daily",
        start_date=date(2026, 10, 9),
        end_date=date(2026, 10, 9),
    )


def test_refresh_synced_marts_refreshes_iv_when_source_is_up_to_date(monkeypatch) -> None:
    build = MagicMock()
    monkeypatch.setattr(sync_marts, "build_features", build)
    run = SyncSourceRun(
        source="tushare",
        plan=[
            SyncTaskItem(
                data_source="tushare",
                endpoint="opt_daily",
                dataset="opt_daily",
                start_date=date(2026, 10, 9),
                end_date=date(2026, 10, 9),
                watermark=date(2026, 10, 9),
                status="UP_TO_DATE",
                is_ready=True,
            )
        ],
        results=[],
        audit_result=None,
    )

    sync_marts.refresh_synced_marts([run], enabled=False)

    build.assert_called_once_with(
        target="settlement_iv_proxy_daily",
        start_date=date(2026, 10, 9),
        end_date=date(2026, 10, 9),
    )


def test_refresh_synced_marts_skips_iv_when_source_failed(monkeypatch) -> None:
    build = MagicMock()
    monkeypatch.setattr(sync_marts, "build_features", build)
    run = SyncSourceRun(
        source="tushare",
        plan=[],
        results=[
            SyncExecutionResult(
                data_source="tushare",
                endpoint="opt_daily",
                start_date=date(2026, 10, 9),
                end_date=date(2026, 10, 9),
                records=0,
                duration_s=0.1,
                status="FAILED",
            )
        ],
        audit_result=None,
    )

    sync_marts.refresh_synced_marts([run], enabled=False)

    build.assert_not_called()
