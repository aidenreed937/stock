"""公共调度入口的任务包展开与严格校验。"""

from __future__ import annotations

import logging

from stock_data.core.task_types import TaskSpec

logger = logging.getLogger(__name__)


def expand_public_task_targets(provider: str, endpoints: list[str] | None = None) -> list[str]:
    """展开任务包，并严格校验每个公共原子任务。"""
    from stock_data.core.task_bundles import resolve_bundle_or_alias as _resolve_bundle_or_alias
    from stock_data.core.task_resolution import (
        expand_task_targets,
        list_available_tasks,
    )

    provider_name = provider.lower()
    if not endpoints:
        return list_available_tasks(provider_name)

    expanded: list[str] = []
    seen: set[str] = set()
    for raw_endpoint in endpoints:
        requested = raw_endpoint.strip()
        if not requested:
            continue
        if provider_name == "industry" and requested in {"industry_tech_bundle", "industry_tech"}:
            logger.warning(
                "[%s] 是跨行业科技观察包，缺少先进封装与 CoWoS；半导体完整同步请使用 "
                "semiconductor_bundle 或 make sync-semiconductor。",
                requested,
            )
        if _resolve_bundle_or_alias(provider_name, requested) is not None:
            candidates = expand_task_targets(provider_name, [requested])
        else:
            candidates = [requested]
        for candidate in candidates:
            task = resolve_public_task(provider_name, candidate)
            if task.task_name not in seen:
                expanded.append(task.task_name)
                seen.add(task.task_name)
    return expanded


def resolve_public_task(provider: str, task_name: str, symbol: str = "") -> TaskSpec:
    """解析 CLI/配置公开任务名，拒绝别名、路径和未注册任务。"""
    from stock_data.core.provider_registry import provider_registry as _provider_registry
    from stock_data.core.task_aliases import (
        DISABLED_TASKS as _DISABLED_TASKS,
    )
    from stock_data.core.task_aliases import (
        LEGACY_ONLY_TASKS as _LEGACY_ONLY_TASKS,
    )
    from stock_data.core.task_aliases import (
        TASK_ALIASES as _ALIASES,
    )
    from stock_data.core.task_bundles import resolve_bundle_or_alias as _resolve_bundle_or_alias
    from stock_data.core.task_manual_specs import CUSTOM_TASKS as _CUSTOM_TASKS
    from stock_data.core.task_resolution import resolve_task

    provider_name = provider.lower()
    requested = task_name.strip()
    if requested in _DISABLED_TASKS:
        hint = (
            "请使用 stock_daily_bar。" if provider_name == "tushare" else "请使用其他已启用任务。"
        )
        raise ValueError(f"项目任务 [{provider_name}/{task_name}] 已停用；{hint}")
    if (provider_name, requested) in _LEGACY_ONLY_TASKS:
        raise ValueError(
            f"项目任务 [{provider_name}/{task_name}] 仅保留历史数据兼容，"
            "当前海关采集请使用 GACC 任务。"
        )
    if _resolve_bundle_or_alias(provider_name, requested) is not None:
        raise ValueError(
            f"[{provider_name}/{task_name}] 是任务包，不是公开原子任务；请在调度入口中展开。"
        )
    if (provider_name, requested) in _ALIASES or "/" in requested:
        raise ValueError(f"[{provider_name}/{task_name}] 不是项目任务名；请使用已注册的短任务名。")
    if (provider_name, requested) not in _CUSTOM_TASKS and requested not in _provider_registry(
        provider_name
    ):
        raise ValueError(
            f"[{provider_name}/{task_name}] 不是已注册的项目任务名；"
            "请使用项目任务注册表中的短任务名。"
        )
    return resolve_task(provider_name, requested, symbol=symbol)


__all__ = ["expand_public_task_targets", "resolve_public_task"]
