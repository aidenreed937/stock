"""同步后定向刷新 Domain Mart 测试。"""

from datetime import date
from unittest.mock import MagicMock

from stock_cli import sync_marts
from stock_data.pipeline.sync import SyncExecutionResult
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

    assert {call.kwargs["target"] for call in build.call_args_list} == {
        "corporate_actions_daily",
        "unlock_pressure_daily",
    }
    assert all(call.kwargs["refresh_marts"] is True for call in build.call_args_list)


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
