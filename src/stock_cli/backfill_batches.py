"""历史回填 CLI 的批次提交辅助函数。"""

from __future__ import annotations

from typing import Any

from stock_core.utils.logger import logger
from stock_data.pipeline.planner import BackfillTask


def create_batch_context(backfiller: Any, enable_batch: bool = True) -> dict[str, Any]:
    """创建共享 Pipeline 的批次上下文并开启攒批模式。"""
    batch_targets = enable_pipeline_batch_mode(backfiller) if enable_batch else []
    return {
        "pipeline": getattr(backfiller, "pipeline", None),
        "fetcher": getattr(backfiller, "fetcher", None),
        "batch_targets": batch_targets,
        "task_count": 1,
        "batch_open": enable_batch,
        "pending_commit": enable_batch,
    }


def skipped_task_summary(task: BackfillTask) -> dict[str, Any]:
    """构造已由本地 Curated 分区覆盖的年度任务摘要。"""
    return {
        "total_days": (task.end_date - task.start_date).days + 1,
        "open_days": 0,
        "synced_days": 0,
        "skipped_days": 1,
        "failed_days": 0,
        "status": "SKIPPED",
        "skip_reason": "curated_partition_exists",
        "data_source": task.data_source,
        "endpoint": task.endpoint,
        "symbol": task.symbol or "全市场",
    }


def commit_batch_contexts(batch_contexts: dict[tuple[str, str], dict[str, Any]]) -> None:
    """提交尚未提交的任务组批次。"""
    for (data_source, endpoint), batch_context in batch_contexts.items():
        if not batch_context["pending_commit"]:
            continue
        logger.info(
            f"提交任务组 [{data_source}/{endpoint}] 攒批数据，"
            f"共 {batch_context['task_count']} 个任务"
        )
        commit_batch_targets(batch_context["batch_targets"])
        batch_context["pending_commit"] = False
        batch_context["batch_open"] = False


def commit_completed_chunk(batch_context: dict[str, Any], task: BackfillTask) -> None:
    """提交年度分块并关闭当前批次，下一块开始前再开启。"""
    logger.info(
        f"提交年度分块 [{task.chunk_index}/{task.chunk_count}] "
        f"[{task.data_source}/{task.endpoint}] 区间: [{task.start_date} ~ {task.end_date}]"
    )
    commit_batch_targets(batch_context["batch_targets"])
    batch_context["pending_commit"] = False
    batch_context["batch_open"] = False


def enable_pipeline_batch_mode(backfiller: Any) -> list[Any]:
    """为 Pipeline 的 Curated 与 RAW 存储开启批次模式。"""
    pipeline = getattr(backfiller, "pipeline", None)
    targets = [getattr(pipeline, "store", None), getattr(pipeline, "raw_store", None)]
    enabled_targets: list[Any] = []
    for target in targets:
        enable_batch_mode = getattr(target, "enable_batch_mode", None)
        if callable(enable_batch_mode):
            enable_batch_mode()
            enabled_targets.append(target)
    return enabled_targets


def commit_batch_targets(targets: list[Any]) -> None:
    """调用各存储目标的批次提交方法。"""
    for target in targets:
        commit = getattr(target, "commit", None)
        if callable(commit):
            commit()


__all__ = [
    "commit_batch_contexts",
    "commit_batch_targets",
    "commit_completed_chunk",
    "create_batch_context",
    "enable_pipeline_batch_mode",
    "skipped_task_summary",
]
