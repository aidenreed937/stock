"""同步完成后的定向 Domain Mart 刷新。"""

from __future__ import annotations

from stock_analytics.pipelines.features import build_features
from stock_data.pipeline.sync_runner import SyncSourceRun

_MART_ENDPOINTS: dict[str, str] = {
    "stk_holdertrade": "corporate_actions_daily",
    "repurchase": "corporate_actions_daily",
    "block_trade": "corporate_actions_daily",
    "share_float": "unlock_pressure_daily",
}
_SUCCESS_STATUSES = {"SUCCESS", "NO_DATA_SOURCE", "NO_DATA_EXPECTED"}


def refresh_synced_marts(runs: list[SyncSourceRun], *, enabled: bool) -> None:
    """按本次成功请求的事件端点刷新受影响 Mart。"""
    if not enabled:
        return
    for run in runs:
        if run.source != "tushare":
            continue
        for target in sorted(set(_MART_ENDPOINTS.values())):
            scoped = [
                result for result in run.results if _MART_ENDPOINTS.get(result.endpoint) == target
            ]
            if not scoped or any(result.status not in _SUCCESS_STATUSES for result in scoped):
                continue
            build_features(
                target=target,
                start_date=min(result.start_date for result in scoped),
                end_date=max(result.end_date for result in scoped),
                refresh_marts=True,
            )


__all__ = ["refresh_synced_marts"]
