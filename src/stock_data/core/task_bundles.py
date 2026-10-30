"""数据源调度任务包门面。"""

from __future__ import annotations

from collections.abc import Mapping

from stock_data.core.task_bundle_aliases import TASK_BUNDLE_ALIASES as _TASK_BUNDLE_ALIASES
from stock_data.core.task_bundle_specs import TASK_BUNDLE_TASKS as _TASK_BUNDLE_TASKS
from stock_data.core.task_bundle_specs import TASK_BUNDLES as _TASK_BUNDLES
from stock_data.core.task_bundle_types import TaskBundle

TASK_BUNDLE_ALIASES = _TASK_BUNDLE_ALIASES
TASK_BUNDLE_TASKS = _TASK_BUNDLE_TASKS
TASK_BUNDLES: dict[tuple[str, str], TaskBundle] = _TASK_BUNDLES


def list_available_bundles(provider: str) -> list[str]:
    """返回指定数据源下已注册的调度任务包名称。"""
    provider_name = provider.lower()
    return [
        bundle.bundle_name
        for (bundle_provider, _), bundle in TASK_BUNDLES.items()
        if bundle_provider == provider_name
    ]


def resolve_bundle_or_alias(provider: str, bundle_name: str) -> TaskBundle | None:
    """解析正式任务包或历史兼容名称。"""
    provider_name = provider.lower()
    requested = bundle_name.strip()
    bundle = TASK_BUNDLES.get((provider_name, requested))
    if bundle is not None:
        return bundle
    alias_tasks = _TASK_BUNDLE_ALIASES.get((provider_name, requested))
    if alias_tasks is None:
        return None
    return TaskBundle(requested, provider_name, alias_tasks)


def resolve_bundle(provider: str, bundle_name: str) -> TaskBundle:
    """解析任务包，并返回其原子任务列表。"""
    bundle = resolve_bundle_or_alias(provider, bundle_name)
    if bundle is None:
        raise ValueError(f"未知任务包 [{provider.lower()}/{bundle_name}]。")
    return bundle


def expand_task_targets(
    provider: str,
    endpoints: list[str] | None = None,
    task_aliases: Mapping[tuple[str, str], str] | None = None,
) -> list[str]:
    """将指定端点中的任务包展开为去重后的原子任务。"""
    provider_name = provider.lower()
    if not endpoints:
        return []

    expanded: list[str] = []
    seen: set[str] = set()
    for endpoint in endpoints:
        requested = endpoint.strip()
        if not requested:
            continue
        bundle = resolve_bundle_or_alias(provider_name, requested)
        targets = bundle.tasks if bundle is not None else (requested,)
        for target in targets:
            canonical_target = (
                task_aliases.get((provider_name, target), target)
                if task_aliases is not None
                else target
            )
            if canonical_target not in seen:
                expanded.append(canonical_target)
                seen.add(canonical_target)
    return expanded


__all__ = [
    "TASK_BUNDLES",
    "TASK_BUNDLE_ALIASES",
    "TASK_BUNDLE_TASKS",
    "TaskBundle",
    "expand_task_targets",
    "list_available_bundles",
    "resolve_bundle",
    "resolve_bundle_or_alias",
]
