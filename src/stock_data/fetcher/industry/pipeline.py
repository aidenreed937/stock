"""垂直产业景气指标 2-Tier ETL 统一同步管道。"""

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.task_executor import execute_single_industry_task

__all__ = ["execute_single_industry_task", "sync_all_industry_metrics"]


def sync_all_industry_metrics(
    raw_dir: Path | str = "data/raw/industry",
    curated_dir: Path | str = "data/curated/industry",
    metrics: list[str] | None = None,
    bundle: str | None = None,
    force: bool = False,
    target_date: date | None = None,
    max_workers: int | None = None,
) -> dict[str, int]:
    """统一同步并落盘垂直产业黄金事实表。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from stock_data.core.task_bundles import expand_task_targets
    from stock_data.pipeline.sync import DailySyncEngine

    endpoints = list(metrics) if metrics else []
    if bundle:
        endpoints.extend(expand_task_targets("industry", [bundle]))

    engine = DailySyncEngine(data_source="industry", max_workers=max_workers)
    plan = engine.build_sync_plan(
        target_date=target_date,
        endpoints=endpoints if endpoints else None,
        force=force,
    )
    pending = [task for task in plan if task.status == "PENDING"]
    if not pending:
        return {}

    results: dict[str, int] = {}
    workers = min(engine.max_workers, len(pending))

    def _worker(task: object) -> tuple[str, int]:
        endpoint = getattr(task, "endpoint", "")
        start_d = getattr(task, "start_date", None)
        end_d = getattr(task, "end_date", None)
        refresh_raw = getattr(task, "refresh_raw_cache", False)
        count = execute_single_industry_task(
            endpoint=endpoint,
            start_date=start_d,
            end_date=end_d,
            force_refresh=force or refresh_raw,
            raw_dir=raw_dir,
            curated_dir=curated_dir,
        )
        return endpoint, count

    if workers <= 1:
        for task in pending:
            endpoint, count = _worker(task)
            if count > 0:
                results[endpoint] = count
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, task) for task in pending]
            for future in as_completed(futures):
                endpoint, count = future.result()
                if count > 0:
                    results[endpoint] = count

    return results
