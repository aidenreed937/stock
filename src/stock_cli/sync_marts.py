"""同步完成后的定向 Domain Mart 刷新。"""

from __future__ import annotations

from datetime import date

from stock_analytics.pipelines.features import build_features
from stock_data.pipeline.sync_runner import SyncSourceRun

_MART_ENDPOINTS: dict[str, str] = {
    "stk_holdertrade": "corporate_actions_daily",
    "repurchase": "corporate_actions_daily",
    "block_trade": "corporate_actions_daily",
    "share_float": "unlock_pressure_daily",
}

# 聪明钱 Mart 依赖市场交易日历、产业资本增持、大宗交易和前十大流通股东。
# 这些输入就绪后必须自动重建，否则新交易日不会出现在 smart_money_daily。
_SMART_MONEY_SOURCE_ENDPOINTS = frozenset(
    {"stock_daily_bar", "stk_holdertrade", "block_trade", "top10_floatholders"}
)
_SMART_MONEY_EVENT_ENDPOINTS = frozenset({"stk_holdertrade", "block_trade"})
_SMART_MONEY_READY_RESULT_STATUSES = {"SUCCESS", "NO_DATA_EXPECTED", "NO_CHANGE", "UP_TO_DATE"}
_SMART_MONEY_BLOCKING_STATUSES = {
    "FAILED",
    "BLOCKED",
    "PARTIAL",
    "MISSING_RANGE",
    "UNSUPPORTED_RANGE",
    "EMPTY",
    "UNKNOWN",
    "SKIPPED",
    "NO_DATA_SOURCE",
}

# 结算价 IV 是由多个源表计算出的 Domain Mart。源表更新后必须自动重建，
# 否则宏观风控只能读到旧的 IV 水位，即使 opt_daily 已经同步成功。
_IV_SOURCE_ENDPOINTS: dict[str, frozenset[str]] = {
    "tushare": frozenset({"opt_daily", "opt_basic", "fund_daily", "index_daily_bar"}),
    "lixinger": frozenset({"national_debt"}),
}
_SUCCESS_STATUSES = {"SUCCESS", "NO_DATA_SOURCE", "NO_DATA_EXPECTED"}
_IV_READY_RESULT_STATUSES = {"SUCCESS", "NO_DATA_EXPECTED", "NO_CHANGE", "UP_TO_DATE"}
_IV_BLOCKING_STATUSES = {
    "FAILED",
    "BLOCKED",
    "PARTIAL",
    "MISSING_RANGE",
    "UNSUPPORTED_RANGE",
    "EMPTY",
    "UNKNOWN",
    "SKIPPED",
    "NO_DATA_SOURCE",
}


def _iv_refresh_window(runs: list[SyncSourceRun]) -> tuple[date, date] | None:
    """判断本轮是否具备重建 IV Mart 的输入，并返回刷新区间。"""
    windows: list[tuple[date, date]] = []
    triggered = False
    for run in runs:
        endpoints = _IV_SOURCE_ENDPOINTS.get(run.source, frozenset())
        if not endpoints:
            continue
        planned = [item for item in run.plan if item.endpoint in endpoints]
        results = [item for item in run.results if item.endpoint in endpoints]
        if not planned and not results:
            continue

        if any(item.status in _IV_BLOCKING_STATUSES for item in planned) or any(
            item.status in _IV_BLOCKING_STATUSES for item in results
        ):
            return None

        ready_plan = [item for item in planned if item.status == "UP_TO_DATE"]
        ready_results = [item for item in results if item.status in _IV_READY_RESULT_STATUSES]
        if not ready_plan and not ready_results:
            continue

        triggered = True
        windows.extend((item.start_date, item.end_date) for item in ready_plan)
        windows.extend((item.start_date, item.end_date) for item in ready_results)

    if not triggered or not windows:
        return None
    return min(start for start, _ in windows), max(end for _, end in windows)


def _refresh_iv_mart(runs: list[SyncSourceRun]) -> None:
    """源任务就绪后自动刷新结算价 IV Mart。"""
    window = _iv_refresh_window(runs)
    if window is None:
        return
    start_date, end_date = window
    build_features(
        target="settlement_iv_proxy_daily",
        start_date=start_date,
        end_date=end_date,
    )


def _smart_money_refresh_window(
    runs: list[SyncSourceRun], endpoints: frozenset[str]
) -> tuple[date, date] | None:
    """判断聪明钱输入是否就绪，并返回重建区间。"""
    windows: list[tuple[date, date]] = []
    triggered = False
    for run in runs:
        if run.source != "tushare":
            continue
        planned = [item for item in run.plan if item.endpoint in endpoints]
        results = [item for item in run.results if item.endpoint in endpoints]
        if not planned and not results:
            continue

        if any(item.status in _SMART_MONEY_BLOCKING_STATUSES for item in planned) or any(
            item.status in _SMART_MONEY_BLOCKING_STATUSES for item in results
        ):
            return None

        ready_plan = [item for item in planned if item.status == "UP_TO_DATE"]
        ready_results = [
            item for item in results if item.status in _SMART_MONEY_READY_RESULT_STATUSES
        ]
        if not ready_plan and not ready_results:
            continue

        triggered = True
        windows.extend((item.start_date, item.end_date) for item in ready_plan)
        windows.extend((item.start_date, item.end_date) for item in ready_results)

    if not triggered or not windows:
        return None
    return min(start for start, _ in windows), max(end for _, end in windows)


def _refresh_smart_money_mart(runs: list[SyncSourceRun], *, corporate_actions_ready: bool) -> None:
    """源任务就绪后重建聪明钱 Mart，并先确保其公司行为输入已刷新。"""
    window = _smart_money_refresh_window(runs, _SMART_MONEY_SOURCE_ENDPOINTS)
    if window is None:
        return
    start_date, end_date = window

    if not corporate_actions_ready:
        event_window = _smart_money_refresh_window(runs, _SMART_MONEY_EVENT_ENDPOINTS)
        if event_window is not None:
            event_start, event_end = event_window
            build_features(
                target="corporate_actions_daily",
                start_date=event_start,
                end_date=event_end,
                refresh_marts=True,
            )

    build_features(
        target="smart_money_daily",
        start_date=start_date,
        end_date=end_date,
    )


def refresh_synced_marts(runs: list[SyncSourceRun], *, enabled: bool) -> None:
    """按本次就绪的源任务刷新受影响 Mart。"""
    # IV Mart 是宏观风控的必需派生输入，不依赖 --refresh-marts 开关。
    _refresh_iv_mart(runs)
    corporate_actions_ready = False
    for run in runs:
        if run.source != "tushare":
            continue
        if not enabled:
            continue
        for target in sorted(set(_MART_ENDPOINTS.values())):
            scoped = [
                result for result in run.results if _MART_ENDPOINTS.get(result.endpoint) == target
            ]
            if not scoped or any(result.status not in _SUCCESS_STATUSES for result in scoped):
                continue
            if target == "corporate_actions_daily":
                corporate_actions_ready = True
            build_features(
                target=target,
                start_date=min(result.start_date for result in scoped),
                end_date=max(result.end_date for result in scoped),
                refresh_marts=True,
            )
    _refresh_smart_money_mart(runs, corporate_actions_ready=corporate_actions_ready)


__all__ = ["refresh_synced_marts"]
