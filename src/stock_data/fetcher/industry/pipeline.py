"""垂直产业景气指标 2-Tier ETL 统一同步管道。"""

import logging
from collections.abc import Sequence
from datetime import date
from inspect import Parameter, signature
from pathlib import Path
from typing import Any, cast

from stock_data.core.runtime import DataRuntimeContext
from stock_data.fetcher.industry.task_executor import execute_single_industry_task

__all__ = ["execute_single_industry_task", "sync_all_industry_metrics"]

logger = logging.getLogger(__name__)

_POWER_DEPENDENCY_STAGES: dict[str, int] = {
    "polysilicon_supply_monthly": 1,
    "polysilicon_inventory_monthly": 1,
    "pv_wafer_monthly": 1,
    "polysilicon_balance": 2,
    "solar_supply_demand": 2,
}

_POWER_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "polysilicon_supply_monthly": ("silicon_wafer_monthly",),
    "polysilicon_inventory_monthly": ("silicon_wafer_monthly",),
    "pv_wafer_monthly": ("silicon_wafer_monthly",),
    "polysilicon_balance": ("polysilicon_supply_monthly", "pv_wafer_monthly"),
    "solar_supply_demand": ("solar_cell_nbs", "solar_capacity"),
}


def _industry_execution_batches(pending: Sequence[object]) -> list[list[object]]:
    """将有 Curated 输入依赖的产业派生任务拆成有序执行批次。"""
    batches: list[list[object]] = [[], [], []]
    for task in pending:
        endpoint = getattr(task, "endpoint", "")
        batches[_POWER_DEPENDENCY_STAGES.get(endpoint, 0)].append(task)
    return [batch for batch in batches if batch]


def sync_all_industry_metrics(
    raw_dir: Path | str = "data/raw/industry",
    curated_dir: Path | str = "data/curated/industry",
    metrics: list[str] | None = None,
    bundle: str | None = None,
    force: bool = False,
    target_date: date | None = None,
    max_workers: int | None = None,
    runtime: DataRuntimeContext | None = None,
) -> dict[str, int]:
    """统一同步并落盘垂直产业黄金事实表。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from stock_data.core.task_bundles import expand_task_targets
    from stock_data.pipeline.sync import DailySyncEngine

    endpoints = list(metrics) if metrics else []
    if bundle:
        endpoints.extend(expand_task_targets("industry", [bundle]))

    engine = DailySyncEngine(
        data_source="industry",
        max_workers=max_workers,
        runtime=runtime,
    )
    plan = engine.build_sync_plan(
        target_date=target_date,
        endpoints=endpoints if endpoints else None,
        force=force,
    )
    pending = [task for task in plan if task.status == "PENDING"]
    if not pending:
        return {}

    results: dict[str, int] = {}
    successful_endpoints: set[str] = set()
    plan_by_endpoint = {task.endpoint: task for task in plan}

    def _worker(task: object) -> tuple[str, Any]:
        endpoint = getattr(task, "endpoint", "")
        start_d = getattr(task, "start_date", None)
        end_d = getattr(task, "end_date", None)
        refresh_raw = getattr(task, "refresh_raw_cache", False)
        parameters = signature(execute_single_industry_task).parameters
        accepts_kwargs = any(param.kind == Parameter.VAR_KEYWORD for param in parameters.values())
        kwargs: dict[str, Any] = {
            "endpoint": endpoint,
            "start_date": start_d,
            "end_date": end_d,
            "force_refresh": force,
            "raw_dir": raw_dir,
            "curated_dir": curated_dir,
        }
        if accepts_kwargs or "refresh_raw_cache" in parameters:
            kwargs["refresh_raw_cache"] = refresh_raw
        if runtime is not None and (accepts_kwargs or "runtime" in parameters):
            kwargs["runtime"] = runtime
        result = cast("Any", execute_single_industry_task)(**kwargs)
        return endpoint, result

    for batch in _industry_execution_batches(pending):
        runnable: list[object] = []
        for task in batch:
            endpoint = getattr(task, "endpoint", "")
            blocked_by: list[str] = []
            for dependency in _POWER_DEPENDENCIES.get(endpoint, ()):
                dependency_task = plan_by_endpoint.get(dependency)
                if dependency_task is None:
                    continue
                if dependency_task.status == "PENDING":
                    if dependency not in successful_endpoints:
                        blocked_by.append(f"{dependency}=未成功")
                elif dependency_task.status != "UP_TO_DATE":
                    blocked_by.append(f"{dependency}={dependency_task.status}")
            if blocked_by:
                logger.warning(
                    "产业派生任务 [%s] 被上游状态阻断: %s", endpoint, ", ".join(blocked_by)
                )
                continue
            runnable.append(task)

        if not runnable:
            continue

        workers = min(engine.max_workers, len(runnable))
        if workers <= 1:
            for task in runnable:
                endpoint, result = _worker(task)
                if result > 0 and getattr(result, "status", "SUCCESS") in {"SUCCESS", "NO_CHANGE"}:
                    results[endpoint] = int(result)
                    if getattr(result, "status", "SUCCESS") == "SUCCESS":
                        successful_endpoints.add(endpoint)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_worker, task) for task in runnable]
                for future in as_completed(futures):
                    endpoint, result = future.result()
                    if result > 0 and getattr(result, "status", "SUCCESS") in {
                        "SUCCESS",
                        "NO_CHANGE",
                    }:
                        results[endpoint] = int(result)
                        if getattr(result, "status", "SUCCESS") == "SUCCESS":
                            successful_endpoints.add(endpoint)

    return results
