"""增量同步应用 Facade。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from stock_data.pipeline.sync import DailySyncEngine, SyncExecutionResult, SyncTaskItem

SYNC_SOURCES: tuple[str, ...] = ("tushare", "yfinance", "lixinger", "fred", "alphavantage")


@dataclass(frozen=True)
class SyncSourceRun:
    """单个数据源的增量同步结果。"""

    source: str
    plan: list[SyncTaskItem]
    results: list[SyncExecutionResult]
    audit_result: dict[str, Any] | None

    @property
    def has_failure(self) -> bool:
        return any(item.status == "FAILED" for item in self.plan) or any(
            item.status == "FAILED" for item in self.results
        )


def run_sync(
    *,
    source: str,
    target_date: date,
    endpoints: list[str] | None = None,
    force: bool = False,
    run_audit_gate: bool = True,
    max_workers: int | None = None,
    target_date_is_explicit: bool = False,
) -> list[SyncSourceRun]:
    """按数据源顺序执行增量同步并返回结构化结果。"""
    sources = SYNC_SOURCES if source == "all" else (source,)
    runs: list[SyncSourceRun] = []
    for data_source in sources:
        engine = DailySyncEngine(data_source=data_source, max_workers=max_workers)
        plan, results, audit_result = engine.sync_daily(
            target_date=target_date,
            endpoints=endpoints,
            force=force,
            run_audit_gate=run_audit_gate,
            target_date_is_explicit=target_date_is_explicit,
        )
        runs.append(
            SyncSourceRun(
                source=data_source,
                plan=plan,
                results=results,
                audit_result=audit_result,
            )
        )
    return runs


__all__ = ["SYNC_SOURCES", "SyncSourceRun", "run_sync"]
