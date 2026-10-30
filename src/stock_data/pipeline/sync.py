"""统一增量数据更新与自动化调度引擎 (DailySyncEngine)。

提供基于水位自动嗅探 (Watermark Sniffing)、发布窗口保护 (Wave Routing)、
多端点并发拉取与自动对账审计的一站式增量更新服务。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from inspect import Parameter, signature
from typing import Any

from stock_core.config.loader import load_data_config
from stock_data.catalog import DataCatalog
from stock_data.core.factory import create_pipeline
from stock_data.core.public_tasks import expand_public_task_targets, resolve_public_task
from stock_data.core.runtime import DataRuntimeContext
from stock_data.core.settings import data_settings
from stock_data.core.task_resolution import (
    expand_task_targets,
    resolve_task,
)
from stock_data.pipeline.report_probe import (
    DEFAULT_YFINANCE_FINANCIAL_PROBE_INTERVAL_DAYS,
    YFinanceFinancialProbeStore,
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

_INDUSTRY_DEPENDENCY_STAGES: dict[str, int] = {
    "polysilicon_supply_monthly": 1,
    "polysilicon_inventory_monthly": 1,
    "pv_wafer_monthly": 1,
    "polysilicon_balance": 2,
    "solar_supply_demand": 2,
}

_INDUSTRY_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "polysilicon_supply_monthly": ("silicon_wafer_monthly",),
    "polysilicon_inventory_monthly": ("silicon_wafer_monthly",),
    "pv_wafer_monthly": ("silicon_wafer_monthly",),
    "polysilicon_balance": ("polysilicon_supply_monthly", "pv_wafer_monthly"),
    "solar_supply_demand": ("solar_cell_nbs", "solar_capacity"),
}


def _industry_execution_batches(pending: list[SyncTaskItem]) -> list[list[SyncTaskItem]]:
    """将有 Curated 输入依赖的产业派生任务拆成有序执行批次。"""
    if not pending or any(task.data_source != "industry" for task in pending):
        return [pending]

    batches: list[list[SyncTaskItem]] = [[], [], []]
    for task in pending:
        stage = _INDUSTRY_DEPENDENCY_STAGES.get(task.endpoint, 0)
        batches[stage].append(task)
    return [batch for batch in batches if batch]


def _industry_dependency_block_reason(
    task: SyncTaskItem,
    plan_by_endpoint: dict[str, SyncTaskItem],
    results_by_endpoint: dict[str, SyncExecutionResult],
) -> str | None:
    """判断产业派生任务是否因本次运行的上游状态而阻断。"""
    dependencies = _INDUSTRY_DEPENDENCIES.get(task.endpoint, ())
    blocked: list[str] = []
    for dependency in dependencies:
        dependency_task = plan_by_endpoint.get(dependency)
        if dependency_task is None:
            continue
        if dependency_task.status == "PENDING":
            result = results_by_endpoint.get(dependency)
            if result is None or result.status != "SUCCESS" or result.records <= 0:
                status = result.status if result is not None else "未执行"
                blocked.append(f"{dependency}={status}")
        elif dependency_task.status != "UP_TO_DATE":
            blocked.append(f"{dependency}={dependency_task.status}")
    if not blocked:
        return None
    return f"上游任务未成功，阻断派生任务: {', '.join(blocked)}"


def _blocked_sync_result(task: SyncTaskItem, reason: str) -> SyncExecutionResult:
    """构造不触发派生执行的阻断结果。"""
    return SyncExecutionResult(
        data_source=task.data_source,
        endpoint=task.endpoint,
        start_date=task.start_date,
        end_date=task.end_date,
        records=0,
        duration_s=0.0,
        status="BLOCKED",
        error=reason,
        symbol=task.symbol,
    )


def _invoke_sync_task(
    task: SyncTaskItem, force_refresh: bool, runtime: DataRuntimeContext
) -> SyncExecutionResult:
    """调用任务执行函数，并兼容旧版测试/扩展的两参数函数。"""
    parameters = signature(_run_sync_task).parameters
    accepts_kwargs = any(param.kind == Parameter.VAR_KEYWORD for param in parameters.values())
    if accepts_kwargs or "runtime" in parameters:
        return _run_sync_task(task, force_refresh, runtime=runtime)
    return _run_sync_task(task, force_refresh)


__all__ = ["DailySyncEngine", "SyncExecutionResult", "SyncTaskItem"]


def _configured_yfinance_financial_probe_interval() -> int:
    try:
        data_cfg = load_data_config()
        return max(
            1,
            int(
                getattr(
                    data_cfg,
                    "yfinance_financial_probe_interval_days",
                    DEFAULT_YFINANCE_FINANCIAL_PROBE_INTERVAL_DAYS,
                )
            ),
        )
    except Exception:
        return DEFAULT_YFINANCE_FINANCIAL_PROBE_INTERVAL_DAYS


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


def _run_sync_task(
    task: SyncTaskItem,
    force_refresh: bool,
    runtime: DataRuntimeContext | None = None,
) -> SyncExecutionResult:
    t0 = time.perf_counter()
    try:
        if task.data_source == "industry":
            from stock_data.fetcher.industry.pipeline import execute_single_industry_task

            industry_result = execute_single_industry_task(
                endpoint=task.endpoint,
                start_date=task.start_date,
                end_date=task.end_date,
                force_refresh=force_refresh,
                refresh_raw_cache=task.refresh_raw_cache,
                runtime=runtime,
            )
            row_count = int(industry_result)
            dur = round(time.perf_counter() - t0, 2)
            outcome_status = getattr(industry_result, "status", None)
            outcome_updated = bool(getattr(industry_result, "updated", row_count > 0))
            outcome_status = outcome_status or ("SUCCESS" if row_count > 0 else "EMPTY")
            outcome_errors = getattr(industry_result, "errors", ())
            if isinstance(outcome_errors, (tuple, list)):
                error_text = "; ".join(str(item) for item in outcome_errors) or None
            else:
                error_text = str(outcome_errors) if outcome_errors else None
            return SyncExecutionResult(
                data_source=task.data_source,
                endpoint=task.endpoint,
                start_date=task.start_date,
                end_date=task.end_date,
                records=row_count,
                duration_s=dur,
                status=outcome_status,
                error=(
                    None
                    if outcome_status == "SUCCESS"
                    else error_text or empty_result_reason(task.data_source, task.endpoint)
                ),
                symbol=task.symbol,
                updated=outcome_updated,
                fetched_periods=tuple(getattr(industry_result, "fetched_periods", ())),
                cached_periods=tuple(getattr(industry_result, "cached_periods", ())),
                missing_periods=tuple(getattr(industry_result, "missing_periods", ())),
            )

        pipeline = create_pipeline(data_source=task.data_source, endpoint=task.endpoint)
        refresh = force_refresh or task.refresh_raw_cache
        df = pipeline.sync_daily_bars(
            symbol=task.symbol,
            start_date=task.start_date,
            end_date=task.end_date,
            use_raw_cache=not refresh,
            force_refresh=refresh,
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
            updated=row_count > 0,
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

    def __init__(
        self,
        data_source: str = "tushare",
        max_workers: int | None = None,
        *,
        runtime: DataRuntimeContext | None = None,
    ) -> None:
        self.data_source = data_source
        self.max_workers = (
            _configured_max_workers(data_source) if max_workers is None else max_workers
        )
        if self.max_workers <= 0:
            raise ValueError("同步并发数必须大于 0")
        self.runtime = runtime or data_settings.runtime_context
        self.catalog = DataCatalog(data_source=data_source, runtime=self.runtime)
        self.report_probe_store = (
            YFinanceFinancialProbeStore(
                self.runtime.cache_root,
                interval_days=_configured_yfinance_financial_probe_interval(),
            )
            if data_source == "yfinance"
            else None
        )

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
            report_probe_decision=(
                self.report_probe_store.decide if self.report_probe_store is not None else None
            ),
        )

    def execute_plan(
        self, plan: list[SyncTaskItem], force_refresh: bool = False
    ) -> list[SyncExecutionResult]:
        """并发执行增量同步任务，并按 Curated 输入依赖分批执行产业派生任务。"""
        pending = [t for t in plan if t.status == "PENDING"]
        if not pending:
            return []

        results: list[SyncExecutionResult] = []
        plan_by_endpoint = {task.endpoint: task for task in plan}
        results_by_endpoint: dict[str, SyncExecutionResult] = {}

        for batch in _industry_execution_batches(pending):
            runnable: list[SyncTaskItem] = []
            for task in batch:
                reason = _industry_dependency_block_reason(
                    task, plan_by_endpoint, results_by_endpoint
                )
                if reason is None:
                    runnable.append(task)
                    continue
                blocked = _blocked_sync_result(task, reason)
                results.append(blocked)
                results_by_endpoint[task.endpoint] = blocked

            if not runnable:
                continue

            workers = min(self.max_workers, len(runnable))
            if workers <= 1:
                batch_results = [
                    _invoke_sync_task(task, force_refresh, self.runtime) for task in runnable
                ]
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [
                        pool.submit(_invoke_sync_task, task, force_refresh, self.runtime)
                        for task in runnable
                    ]
                    batch_results = [fut.result() for fut in as_completed(futures)]
            results.extend(batch_results)
            results_by_endpoint.update({result.endpoint: result for result in batch_results})

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

        if self.report_probe_store is not None:
            latest_watermarks: dict[tuple[str, str], date | None] = {}
            probe_targets: dict[tuple[str, str], date] = {}
            symbols_by_dataset: dict[str, set[str]] = {}
            result_tasks: dict[tuple[str, str], Any] = {}
            for result in exec_results:
                if not result.symbol:
                    continue
                try:
                    task = resolve_task(self.data_source, result.endpoint)
                except Exception:
                    continue
                if task.query_mode != "period":
                    continue
                probe_targets[(result.endpoint, result.symbol)] = result.end_date
                symbols_by_dataset.setdefault(task.dataset, set()).add(result.symbol)
                result_tasks[(result.endpoint, result.symbol)] = task
            watermarks_by_dataset = {
                dataset: _symbol_watermarks(
                    self.catalog,
                    self.data_source,
                    dataset,
                    sorted(symbols),
                )
                for dataset, symbols in symbols_by_dataset.items()
            }
            for result_key, task in result_tasks.items():
                _, symbol = result_key
                latest_watermarks[result_key] = watermarks_by_dataset[task.dataset].get(symbol)
            self.report_probe_store.record_results(
                exec_results,
                latest_watermarks=latest_watermarks,
                probe_targets=probe_targets,
            )

        audit_result = _run_incremental_audit(self.data_source, exec_results, run_audit_gate)

        return plan, exec_results, audit_result
