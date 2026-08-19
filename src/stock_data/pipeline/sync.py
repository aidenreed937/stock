"""统一增量数据更新与自动化调度引擎 (DailySyncEngine)。

提供基于水位自动嗅探 (Watermark Sniffing)、发布窗口保护 (Wave Routing)、
多端点并发拉取与自动对账审计的一站式增量更新服务。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any

from stock_core.config.loader import load_data_config
from stock_data.catalog import DataCatalog
from stock_data.core.factory import create_pipeline
from stock_data.core.task_registry import (
    expand_public_task_targets,
    expand_task_targets,
    resolve_public_task,
    resolve_task,
)
from stock_data.pipeline.scheduler import DataUpdateScheduler as _DataUpdateScheduler
from stock_data.pipeline.sync_helpers import (
    configured_max_workers as _configured_max_workers_impl,
)
from stock_data.pipeline.sync_helpers import (
    disabled_endpoints as _disabled_endpoints_impl,
)
from stock_data.pipeline.sync_helpers import (
    next_increment_start as _next_increment_start_impl,
)
from stock_data.pipeline.sync_helpers import (
    parse_watermark_value as _parse_watermark_value_impl,
)
from stock_data.pipeline.sync_helpers import (
    schedule_endpoint as _schedule_endpoint_impl,
)
from stock_data.pipeline.sync_helpers import (
    sniff_watermarks as _sniff_watermarks_impl,
)
from stock_data.pipeline.sync_helpers import (
    symbol_base_date as _symbol_base_date_impl,
)
from stock_data.pipeline.sync_helpers import (
    symbol_refresh_watermarks as _symbol_refresh_watermarks_impl,
)
from stock_data.pipeline.sync_helpers import (
    symbol_watermark as _symbol_watermark_impl,
)
from stock_data.pipeline.sync_helpers import (
    symbol_watermarks as _symbol_watermarks_impl,
)
from stock_data.pipeline.sync_helpers import (
    sync_symbols_for_task as _sync_symbols_for_task_impl,
)
from stock_data.pipeline.sync_helpers import (
    watermark_date_column as _watermark_date_column_impl,
)
from stock_data.pipeline.sync_models import SyncExecutionResult, SyncTaskItem
from stock_data.pipeline.sync_planner import build_sync_plan as _build_sync_plan_impl
from stock_data.pipeline.sync_status import empty_result_reason, empty_result_status

DataUpdateScheduler = _DataUpdateScheduler

logger = logging.getLogger(__name__)

__all__ = ["DailySyncEngine", "SyncExecutionResult", "SyncTaskItem"]


def _sniff_watermarks(
    catalog: DataCatalog, data_source: str, endpoints: list[str] | None = None
) -> dict[str, date | None]:
    return _sniff_watermarks_impl(
        catalog,
        data_source,
        endpoints,
        disabled_endpoints_fn=_disabled_endpoints,
        watermark_date_column_fn=_watermark_date_column,
        expand_task_targets_fn=expand_task_targets,
        resolve_task_fn=resolve_task,
    )


def _disabled_endpoints(data_source: str) -> set[str]:
    return _disabled_endpoints_impl(data_source, load_config=load_data_config)


def _configured_max_workers(data_source: str) -> int:
    return _configured_max_workers_impl(data_source, load_config=load_data_config)


def _sync_symbols_for_task(data_source: str, endpoint: str) -> list[str]:
    return _sync_symbols_for_task_impl(
        data_source,
        endpoint,
        load_config=load_data_config,
        resolve_task_fn=resolve_task,
    )


def _schedule_endpoint(data_source: str, endpoint: str, symbol: str) -> str:
    return _schedule_endpoint_impl(data_source, endpoint, symbol)


def _watermark_date_column(data_source: str, endpoint: str) -> str:
    return _watermark_date_column_impl(data_source, endpoint)


def _next_increment_start(watermark: date, data_source: str, endpoint: str, frequency: str) -> date:
    return _next_increment_start_impl(watermark, data_source, endpoint, frequency)


def _parse_watermark_value(value: Any) -> date | None:
    return _parse_watermark_value_impl(value)


def _symbol_watermark(
    catalog: DataCatalog, data_source: str, dataset: str, symbol: str
) -> date | None:
    return _symbol_watermark_impl(catalog, data_source, dataset, symbol)


def _symbol_watermarks(
    catalog: DataCatalog,
    data_source: str,
    dataset: str,
    symbols: list[str],
) -> dict[str, date | None]:
    return _symbol_watermarks_impl(catalog, data_source, dataset, symbols)


def _symbol_refresh_watermarks(
    catalog: DataCatalog,
    data_source: str,
    dataset: str,
    symbols: list[str],
) -> dict[str, date | None]:
    return _symbol_refresh_watermarks_impl(catalog, data_source, dataset, symbols)


def _symbol_base_date(data_source: str, symbol: str, endpoint: str = "") -> date | None:
    return _symbol_base_date_impl(
        data_source,
        symbol,
        endpoint,
        load_config=load_data_config,
    )


def _run_sync_task(task: SyncTaskItem, force_refresh: bool) -> SyncExecutionResult:
    t0 = time.perf_counter()
    try:
        pipeline = create_pipeline(data_source=task.data_source, endpoint=task.endpoint)
        df = pipeline.sync_daily_bars(
            symbol=task.symbol,
            start_date=task.start_date,
            end_date=task.end_date,
            use_raw_cache=not force_refresh,
            force_refresh=force_refresh,
        )
        dur = round(time.perf_counter() - t0, 2)
        row_count = len(df) if df is not None and not df.is_empty() else 0
        return SyncExecutionResult(
            data_source=task.data_source,
            endpoint=task.endpoint,
            start_date=task.start_date,
            end_date=task.end_date,
            records=row_count,
            duration_s=dur,
            status=(
                "SUCCESS" if row_count > 0 else empty_result_status(task.data_source, task.endpoint)
            ),
            error=None if row_count > 0 else empty_result_reason(task.data_source, task.endpoint),
            symbol=task.symbol,
        )
    except Exception as e:
        dur = round(time.perf_counter() - t0, 2)
        label = f"{task.data_source}/{task.endpoint}"
        if task.symbol:
            label = f"{label}/{task.symbol}"
        logger.error(f"增量同步任务 [{label}] 异常: {e}")
        return SyncExecutionResult(
            data_source=task.data_source,
            endpoint=task.endpoint,
            start_date=task.start_date,
            end_date=task.end_date,
            records=0,
            duration_s=dur,
            status="FAILED",
            error=str(e),
            symbol=task.symbol,
        )


def _run_incremental_audit(
    data_source: str,
    exec_results: list[SyncExecutionResult],
    enabled: bool,
) -> dict[str, Any] | None:
    """仅为 TuShare 日行情同步触发 A 股专用对账。"""
    stock_bar_results = [
        result
        for result in exec_results
        if result.status == "SUCCESS" and result.endpoint == "stock_daily_bar"
    ]
    if not enabled:
        return None
    if data_source != "tushare" or not stock_bar_results:
        if any(result.status == "SUCCESS" for result in exec_results):
            logger.info(
                "增量同步包含非 TuShare 数据源或非 stock_daily_bar 任务，跳过 A 股专用对账审计"
            )
        return None

    try:
        from stock_data.governance.audit.reconciliation import run_audit

        audit_date = stock_bar_results[0].end_date
        logger.info(f"增量同步完成，正在触发 [{audit_date}] 质量对账门禁...")
        return run_audit(target_date=audit_date, data_source=data_source, quiet=True)
    except Exception as e:
        logger.warning(f"增量后自动审计异常: {e}")
        return None


class DailySyncEngine:
    """增量数据同步与自愈引擎。"""

    def __init__(self, data_source: str = "tushare", max_workers: int | None = None) -> None:
        self.data_source = data_source
        self.max_workers = (
            _configured_max_workers(data_source) if max_workers is None else max_workers
        )
        if self.max_workers <= 0:
            raise ValueError("同步并发数必须大于 0")
        self.catalog = DataCatalog(data_source=data_source)

    def sniff_watermarks(self, endpoints: list[str] | None = None) -> dict[str, date | None]:
        """逆序探测指定端点的最新落盘交易日水位 (Watermark)。"""
        return _sniff_watermarks(self.catalog, self.data_source, endpoints)

    def build_sync_plan(
        self,
        target_date: date | None = None,
        endpoints: list[str] | None = None,
        force: bool = False,
        current_datetime: datetime | None = None,
        target_date_is_explicit: bool = True,
    ) -> list[SyncTaskItem]:
        """结合落盘水位与更新时间窗口，生成最小必要增量同步任务计划。"""
        public_endpoints = expand_public_task_targets(self.data_source, endpoints)
        return _build_sync_plan_impl(
            catalog=self.catalog,
            data_source=self.data_source,
            target_date=target_date,
            endpoints=public_endpoints,
            force=force,
            current_datetime=current_datetime,
            target_date_is_explicit=target_date_is_explicit,
            sniff_watermarks=self.sniff_watermarks,
            disabled_endpoints=_disabled_endpoints,
            sync_symbols_for_task=_sync_symbols_for_task,
            symbol_watermarks=_symbol_watermarks,
            symbol_refresh_watermarks=_symbol_refresh_watermarks,
            schedule_endpoint=_schedule_endpoint,
            next_increment_start=_next_increment_start,
            symbol_base_date=_symbol_base_date,
            expand_task_targets_fn=expand_task_targets,
            resolve_task_fn=resolve_public_task,
        )

    def execute_plan(
        self, plan: list[SyncTaskItem], force_refresh: bool = False
    ) -> list[SyncExecutionResult]:
        """并发执行增量同步任务。"""
        pending = [t for t in plan if t.status == "PENDING"]
        if not pending:
            return []

        results: list[SyncExecutionResult] = []

        workers = min(self.max_workers, len(pending))
        if workers <= 1:
            for task in pending:
                results.append(_run_sync_task(task, force_refresh))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_run_sync_task, task, force_refresh) for task in pending]
                for fut in as_completed(futures):
                    results.append(fut.result())

        return results

    def sync_daily(
        self,
        target_date: date | None = None,
        endpoints: list[str] | None = None,
        force: bool = False,
        run_audit_gate: bool = True,
        target_date_is_explicit: bool = True,
    ) -> tuple[list[SyncTaskItem], list[SyncExecutionResult], dict[str, Any] | None]:
        """一站式完成增量计划生成、执行与质量对账。"""
        t_target = target_date or date.today()
        plan = self.build_sync_plan(
            target_date=t_target,
            endpoints=endpoints,
            force=force,
            target_date_is_explicit=target_date_is_explicit,
        )
        exec_results = self.execute_plan(plan, force_refresh=force)

        audit_result = _run_incremental_audit(self.data_source, exec_results, run_audit_gate)

        return plan, exec_results, audit_result
