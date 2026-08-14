"""统一增量数据更新与自动化调度引擎 (DailySyncEngine)。

提供基于水位自动嗅探 (Watermark Sniffing)、发布窗口保护 (Wave Routing)、
多端点并发拉取与自动对账审计的一站式增量更新服务。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
import time
from typing import Any

from stock.data.catalog import DataCatalog
from stock.data.factory import create_pipeline
from stock.data.task_registry import list_available_tasks, resolve_task
from stock.data.update_scheduler import DataUpdateScheduler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncTaskItem:
    """单个端点增量同步任务项。"""

    data_source: str
    endpoint: str
    dataset: str
    start_date: date
    end_date: date
    watermark: date | None
    status: str
    is_ready: bool
    reason: str = ""


@dataclass
class SyncExecutionResult:
    """增量同步执行统计结果。"""

    data_source: str
    endpoint: str
    start_date: date
    end_date: date
    records: int
    duration_s: float
    status: str
    error: str | None = None


class DailySyncEngine:
    """增量数据同步与自愈引擎。"""

    def __init__(self, data_source: str = "tushare", max_workers: int = 4) -> None:
        self.data_source = data_source
        self.max_workers = max_workers
        self.catalog = DataCatalog(data_source=data_source)

    def sniff_watermarks(self, endpoints: list[str] | None = None) -> dict[str, date | None]:
        """逆序探测指定端点的最新落盘交易日水位 (Watermark)。"""
        targets = endpoints or list_available_tasks(self.data_source)
        watermarks: dict[str, date | None] = {}
        for ep in targets:
            try:
                task = resolve_task(self.data_source, ep)
                dataset = task.dataset
                latest_dates = self.catalog.latest_trade_dates(dataset=dataset, n=1)
                watermarks[ep] = latest_dates[0] if latest_dates else None
            except Exception as e:
                logger.debug(f"探测端点 [{ep}] 水位异常: {e}")
                watermarks[ep] = None
        return watermarks

    def build_sync_plan(
        self,
        target_date: date | None = None,
        endpoints: list[str] | None = None,
        force: bool = False,
        current_datetime: datetime | None = None,
    ) -> list[SyncTaskItem]:
        """结合落盘水位与更新时间窗口，生成最小必要增量同步任务计划。"""
        t_target = target_date or date.today()
        targets = endpoints or list_available_tasks(self.data_source)
        watermarks = self.sniff_watermarks(targets)

        plan: list[SyncTaskItem] = []
        for ep in targets:
            task = resolve_task(self.data_source, ep)
            w_date = watermarks.get(ep)
            ready = DataUpdateScheduler.is_data_ready(
                endpoint=ep,
                target_date=t_target,
                current_datetime=current_datetime,
                data_source=self.data_source,
            )

            if not ready and not force:
                meta = DataUpdateScheduler.get_endpoint_update_meta(self.data_source, ep)
                plan.append(
                    SyncTaskItem(
                        data_source=self.data_source,
                        endpoint=ep,
                        dataset=task.dataset,
                        start_date=t_target,
                        end_date=t_target,
                        watermark=w_date,
                        status="SKIPPED",
                        is_ready=False,
                        reason=f"窗口未到 ({meta.update_time} T+{meta.update_delay_days})",
                    )
                )
                continue

            if not force and w_date is not None and w_date >= t_target:
                plan.append(
                    SyncTaskItem(
                        data_source=self.data_source,
                        endpoint=ep,
                        dataset=task.dataset,
                        start_date=t_target,
                        end_date=t_target,
                        watermark=w_date,
                        status="UP_TO_DATE",
                        is_ready=True,
                        reason="已是最新",
                    )
                )
                continue

            # 推导待补齐起始日期（自愈缺口）
            if w_date is not None:
                start_d = w_date + timedelta(days=1)
                # 若水位已经是当天或更晚，且处于 force 模式，覆盖更新当天
                if start_d > t_target:
                    start_d = t_target
            else:
                start_d = t_target

            plan.append(
                SyncTaskItem(
                    data_source=self.data_source,
                    endpoint=ep,
                    dataset=task.dataset,
                    start_date=start_d,
                    end_date=t_target,
                    watermark=w_date,
                    status="PENDING",
                    is_ready=True,
                    reason=f"待增量 ({start_d} ~ {t_target})",
                )
            )
        return plan

    def execute_plan(
        self, plan: list[SyncTaskItem], force_refresh: bool = False
    ) -> list[SyncExecutionResult]:
        """并发执行增量同步任务。"""
        pending = [t for t in plan if t.status == "PENDING"]
        if not pending:
            return []

        results: list[SyncExecutionResult] = []

        def _run_single(task: SyncTaskItem) -> SyncExecutionResult:
            t0 = time.perf_counter()
            try:
                pipeline = create_pipeline(data_source=task.data_source, endpoint=task.endpoint)
                df = pipeline.sync_daily_bars(
                    symbol="",
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
                    status="SUCCESS" if row_count > 0 else "NO_DATA",
                )
            except Exception as e:
                dur = round(time.perf_counter() - t0, 2)
                logger.error(f"增量同步任务 [{task.data_source}/{task.endpoint}] 异常: {e}")
                return SyncExecutionResult(
                    data_source=task.data_source,
                    endpoint=task.endpoint,
                    start_date=task.start_date,
                    end_date=task.end_date,
                    records=0,
                    duration_s=dur,
                    status="FAILED",
                    error=str(e),
                )

        workers = min(self.max_workers, len(pending))
        if workers <= 1:
            for task in pending:
                results.append(_run_single(task))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_run_single, task) for task in pending]
                for fut in as_completed(futures):
                    results.append(fut.result())

        return results

    def sync_daily(
        self,
        target_date: date | None = None,
        endpoints: list[str] | None = None,
        force: bool = False,
        run_audit_gate: bool = True,
    ) -> tuple[list[SyncTaskItem], list[SyncExecutionResult], dict[str, Any] | None]:
        """一站式完成增量计划生成、执行与质量对账。"""
        t_target = target_date or date.today()
        plan = self.build_sync_plan(target_date=t_target, endpoints=endpoints, force=force)
        exec_results = self.execute_plan(plan, force_refresh=force)

        audit_result: dict[str, Any] | None = None
        if run_audit_gate and any(r.status == "SUCCESS" for r in exec_results):
            try:
                from stock.data.audit.reconciliation import run_audit

                logger.info(f"增量同步完成，正在触发 [{t_target}] 质量对账门禁...")
                audit_result = run_audit(target_date=t_target, data_source=self.data_source, quiet=True)
            except Exception as e:
                logger.warning(f"增量后自动审计异常: {e}")

        return plan, exec_results, audit_result
