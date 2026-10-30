"""增量同步应用 Facade。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any

from stock_core.utils.logger import logger
from stock_data.core.runtime import DataRuntimeContext
from stock_data.pipeline.derived_refresh import (
    refresh_semiconductor_equipment_gm_multi,
    refresh_sw_2021_industry_golden,
    refresh_tushare_index_member_versioned,
)
from stock_data.pipeline.sync import DailySyncEngine, SyncExecutionResult, SyncTaskItem
from stock_data.pipeline.sync_helpers import configured_source_workers

SYNC_SOURCES: tuple[str, ...] = (
    "tushare",
    "lixinger",
    "fred",
    "alphavantage",
    "industry",
)


@dataclass(frozen=True)
class SyncSourceRun:
    """单个数据源的增量同步结果。"""

    source: str
    plan: list[SyncTaskItem]
    results: list[SyncExecutionResult]
    audit_result: dict[str, Any] | None

    @property
    def has_failure(self) -> bool:
        failure_statuses = {
            "FAILED",
            "BLOCKED",
            "PARTIAL",
            "MISSING_RANGE",
            "UNSUPPORTED_RANGE",
            "NO_CHANGE",
            "EMPTY",
            "UNKNOWN",
        }
        return any(item.status in failure_statuses for item in self.plan) or any(
            item.status in failure_statuses for item in self.results
        )


def _sync_one_source(
    data_source: str,
    *,
    target_date: date,
    endpoints: list[str] | None,
    force: bool,
    run_audit_gate: bool,
    max_workers: int | None,
    target_date_is_explicit: bool,
    runtime: DataRuntimeContext | None,
) -> SyncSourceRun:
    """执行单个数据源同步；跨数据源并发由调用方控制。"""
    try:
        engine = DailySyncEngine(
            data_source=data_source,
            max_workers=max_workers,
            runtime=runtime,
        )
        plan, results, audit_result = engine.sync_daily(
            target_date=target_date,
            endpoints=endpoints,
            force=force,
            run_audit_gate=run_audit_gate,
            target_date_is_explicit=target_date_is_explicit,
        )
        return SyncSourceRun(
            source=data_source,
            plan=plan,
            results=results,
            audit_result=audit_result,
        )
    except Exception as exc:
        error = f"数据源 [{data_source}] 增量同步异常: {exc}"
        logger.error(error)
        return SyncSourceRun(
            source=data_source,
            plan=[],
            results=[
                SyncExecutionResult(
                    data_source=data_source,
                    endpoint="__source_sync__",
                    start_date=target_date,
                    end_date=target_date,
                    records=0,
                    duration_s=0.0,
                    status="FAILED",
                    error=error,
                )
            ],
            audit_result=None,
        )


def _refresh_derived_results(
    run: SyncSourceRun,
    *,
    runtime: DataRuntimeContext | None,
) -> SyncSourceRun:
    """串行刷新跨源派生表，避免并发覆写共享产物。"""
    results = list(run.results)
    if run.source == "tushare":
        golden_result = refresh_sw_2021_industry_golden(
            run.source,
            run.plan,
            results,
            runtime=runtime,
        )
        if golden_result is not None:
            results.append(golden_result)
        derived_result = refresh_tushare_index_member_versioned(
            run.plan,
            results,
            runtime=runtime,
        )
        if derived_result is not None:
            results.append(derived_result)
    elif run.source == "lixinger":
        golden_result = refresh_sw_2021_industry_golden(
            run.source,
            run.plan,
            results,
            runtime=runtime,
        )
        if golden_result is not None:
            results.append(golden_result)
    elif run.source == "industry":
        equipment_gm_result = refresh_semiconductor_equipment_gm_multi(
            run.plan,
            results,
            runtime=runtime,
        )
        if equipment_gm_result is not None:
            results.append(equipment_gm_result)
    return SyncSourceRun(
        source=run.source,
        plan=run.plan,
        results=results,
        audit_result=run.audit_result,
    )


def run_sync(
    *,
    source: str,
    target_date: date,
    endpoints: list[str] | None = None,
    force: bool = False,
    run_audit_gate: bool = True,
    max_workers: int | None = None,
    source_workers: int | None = None,
    target_date_is_explicit: bool = False,
    runtime: DataRuntimeContext | None = None,
) -> list[SyncSourceRun]:
    """按数据源并发执行增量同步，并按固定顺序返回结果。"""
    sources = SYNC_SOURCES if source == "all" else (source,)
    if source_workers is None:
        source_workers = configured_source_workers()
    if source_workers <= 0:
        raise ValueError("数据源并发数必须大于 0")

    if len(sources) > 1 and source_workers > 1:
        worker_count = min(source_workers, len(sources))
        logger.info(f"跨数据源并行同步启动: workers={worker_count}, sources={list(sources)}")
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="sync-source",
        ) as executor:
            futures = {
                data_source: executor.submit(
                    _sync_one_source,
                    data_source,
                    target_date=target_date,
                    endpoints=endpoints,
                    force=force,
                    run_audit_gate=run_audit_gate,
                    max_workers=max_workers,
                    target_date_is_explicit=target_date_is_explicit,
                    runtime=runtime,
                )
                for data_source in sources
            }
            runs = [futures[data_source].result() for data_source in sources]
    else:
        runs = [
            _sync_one_source(
                data_source,
                target_date=target_date,
                endpoints=endpoints,
                force=force,
                run_audit_gate=run_audit_gate,
                max_workers=max_workers,
                target_date_is_explicit=target_date_is_explicit,
                runtime=runtime,
            )
            for data_source in sources
        ]

    return [_refresh_derived_results(run, runtime=runtime) for run in runs]


__all__ = ["SYNC_SOURCES", "SyncSourceRun", "run_sync"]
