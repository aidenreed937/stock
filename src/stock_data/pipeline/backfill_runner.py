"""历史回填应用 Facade。"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from stock_core.config.loader import load_data_config
from stock_core.utils.logger import logger
from stock_data.core.task_registry import is_per_symbol_task
from stock_data.pipeline import backfill_batches
from stock_data.pipeline.planner import BackfillPlanner, BackfillTask


@dataclass(frozen=True)
class BackfillRequest:
    """一次历史回填运行请求。"""

    data_source: str | None = None
    endpoint: str | None = None
    symbol: str | None = None
    universe: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    config: str | None = None
    force_refresh: bool = False
    max_workers: int | None = None


def parse_backfill_date(value: str | None) -> date | None:
    """解析回填配置支持的日期格式。"""
    if not value:
        return None
    clean = value.strip().lower()
    if clean == "today":
        return date.today()
    match = re.fullmatch(r"today-(\d+)", clean)
    if match:
        return date.today() - timedelta(days=int(match.group(1)))
    return datetime.strptime(clean.replace("-", ""), "%Y%m%d").date()


def resolve_universe_symbols(universe_name: str | None) -> str | None:
    """从 Universe 配置文件中解析标的列表。"""
    if not universe_name:
        return None
    universe_path = Path(f"config/universe/{universe_name}.yaml")
    if not universe_path.exists():
        return None
    try:
        with universe_path.open("r", encoding="utf-8") as handle:
            universe_data = yaml.safe_load(handle)
        if not isinstance(universe_data, dict):
            return None
        definition = universe_data.get("universe", {})
        if not isinstance(definition, dict):
            return None
        symbols = definition.get("symbols", [])
        if isinstance(symbols, list) and symbols:
            return ",".join(str(symbol) for symbol in symbols)
        if any(key in definition for key in ("a_shares", "global", "macro")):
            return "watchlist"
    except Exception as error:
        logger.warning(f"加载 Universe 股票池 [{universe_name}] 失败: {error}")
    return None


def _create_backfiller(
    task: BackfillTask,
    *,
    pipeline: Any | None = None,
    fetcher: Any | None = None,
) -> Any:
    from stock_data.pipeline.backfill import HistoricalBackfiller

    kwargs: dict[str, Any] = {
        "data_source": task.data_source,
        "endpoint": task.endpoint,
        "symbol": task.symbol,
    }
    if pipeline is not None:
        kwargs["pipeline"] = pipeline
    if fetcher is not None:
        kwargs["fetcher"] = fetcher
    return HistoricalBackfiller(**kwargs)


def _execute_one_task(
    backfiller: Any,
    task: BackfillTask,
    *,
    task_position: tuple[int, int],
    force_refresh: bool,
    workers: int,
) -> dict[str, Any]:
    task_index, total_tasks = task_position
    logger.info(
        f"===> [{task_index}/{total_tasks}] 执行任务 [{task.data_source}/{task.endpoint}] "
        f"标的: [{task.symbol or '全市场'}] 区间: [{task.start_date} ~ {task.end_date}]"
    )
    summary = backfiller.backfill_range(
        task.start_date,
        task.end_date,
        force_refresh=force_refresh,
        max_workers=workers,
    )
    summary_data: dict[str, Any] = dict(summary) if isinstance(summary, dict) else {}
    summary_data.update(
        data_source=task.data_source,
        endpoint=task.endpoint,
        symbol=task.symbol or "全市场",
    )
    return summary_data


def execute_planned_tasks(
    tasks: list[BackfillTask], *, force_refresh: bool, workers: int
) -> list[dict[str, Any]]:
    """以攒批事务模式驱动规划任务，支持按标的并发和年度分块提交。"""
    batch_contexts: dict[tuple[str, str], dict[str, Any]] = {}
    task_groups: dict[tuple[str, str], list[tuple[int, BackfillTask]]] = {}
    backfillers_by_index: dict[int, Any] = {}
    summaries_by_index: dict[int, dict[str, Any]] = {}
    try:
        for index, task in enumerate(tasks, 1):
            if task.skip_existing and not force_refresh:
                summaries_by_index[index] = backfill_batches.skipped_task_summary(task)
                logger.info(
                    f"===> [{index}/{len(tasks)}] 跳过已存在分块 [{task.data_source}/{task.endpoint}] "
                    f"区间: [{task.start_date} ~ {task.end_date}]"
                )
                continue
            context_key = (task.data_source, task.endpoint)
            batch_context = batch_contexts.get(context_key)
            if batch_context is None:
                backfiller = _create_backfiller(task)
                batch_context = backfill_batches.create_batch_context(backfiller)
                batch_contexts[context_key] = batch_context
            else:
                batch_context["task_count"] += 1
                backfiller = _create_backfiller(
                    task,
                    pipeline=batch_context["pipeline"],
                    fetcher=batch_context["fetcher"],
                )
            backfillers_by_index[index] = backfiller
            task_groups.setdefault(context_key, []).append((index, task))

        for context_key, grouped_tasks in task_groups.items():
            batch_context = batch_contexts[context_key]
            data_source, endpoint = context_key
            can_parallel = workers > 1 and is_per_symbol_task(data_source, endpoint)
            can_parallel = can_parallel and not any(task.is_chunked for _, task in grouped_tasks)
            if can_parallel and len(grouped_tasks) > 1:
                group_workers = min(workers, 8)
                logger.info(
                    f"任务组 [{data_source}/{endpoint}] 启用波内并发，"
                    f"Worker 数: {group_workers}，任务数: {len(grouped_tasks)}"
                )
                with ThreadPoolExecutor(max_workers=group_workers) as executor:
                    futures = {
                        executor.submit(
                            _execute_one_task,
                            backfillers_by_index[index],
                            task,
                            task_position=(index, len(tasks)),
                            force_refresh=force_refresh,
                            workers=workers,
                        ): index
                        for index, task in grouped_tasks
                    }
                    for future in as_completed(futures):
                        summaries_by_index[futures[future]] = future.result()
            else:
                for index, task in grouped_tasks:
                    if not batch_context["batch_open"]:
                        batch_context["batch_targets"] = (
                            backfill_batches.enable_pipeline_batch_mode(backfillers_by_index[index])
                        )
                        batch_context["batch_open"] = True
                        batch_context["pending_commit"] = True
                    summaries_by_index[index] = _execute_one_task(
                        backfillers_by_index[index],
                        task,
                        task_position=(index, len(tasks)),
                        force_refresh=force_refresh,
                        workers=workers,
                    )
                    if task.is_chunked:
                        backfill_batches.commit_completed_chunk(batch_context, task)
    finally:
        backfill_batches.commit_batch_contexts(batch_contexts)
    return [summaries_by_index[index] for index in range(1, len(tasks) + 1)]


def run_backfill(
    request: BackfillRequest,
    *,
    data_cfg: Any | None = None,
) -> list[dict[str, Any]]:
    """解析配置、规划并执行一次历史回填。"""
    from stock_data.pipeline.backfill import _load_backfill_yaml_config

    yaml_config = (
        _load_backfill_yaml_config(request.config)
        if request.config
        else _load_backfill_yaml_config()
    )
    config = data_cfg or load_data_config()
    data_source = (
        request.data_source
        or yaml_config.get("data_source")
        or yaml_config.get("default_data_source", "tushare")
    )
    symbol = (
        request.symbol
        or resolve_universe_symbols(request.universe)
        or yaml_config.get("symbol")
        or yaml_config.get("default_symbol")
    )
    raw_endpoints = (
        request.endpoint or yaml_config.get("endpoint") or yaml_config.get("default_endpoint")
    )
    endpoints = (
        [endpoint.strip() for endpoint in raw_endpoints.split(",") if endpoint.strip()]
        if raw_endpoints
        else None
    )
    force_refresh = request.force_refresh or yaml_config.get("force_refresh", False)
    start_config = yaml_config.get("start_date") or yaml_config.get("default_start_date")
    end_config = yaml_config.get("end_date") or yaml_config.get("default_end_date")
    start_date = request.start_date or parse_backfill_date(start_config) or date(2024, 1, 1)
    end_date = request.end_date or parse_backfill_date(end_config) or date.today()
    start_specified = request.start_date is not None or bool(start_config)
    workers = request.max_workers or yaml_config.get("max_workers")
    if workers is None and config:
        workers = getattr(
            config.concurrency,
            f"{data_source}_max_workers",
            config.concurrency.default_max_workers,
        )
    workers = workers or 1
    tasks = BackfillPlanner.plan_tasks(
        data_source=data_source,
        endpoints=endpoints,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        start_specified=start_specified,
        data_cfg=config,
        force_refresh=force_refresh,
    )
    if not tasks:
        logger.warning(f"数据源 [{data_source}] 未规划出任何有效回填任务")
        return []
    logger.info(f"[{data_source}] 回填任务规划完成，共生成 {len(tasks)} 个原子回填任务。")
    return execute_planned_tasks(tasks, force_refresh=force_refresh, workers=workers)


run_backfill_range = run_backfill


__all__ = [
    "BackfillRequest",
    "execute_planned_tasks",
    "parse_backfill_date",
    "resolve_universe_symbols",
    "run_backfill",
    "run_backfill_range",
]
