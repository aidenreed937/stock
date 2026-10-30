"""项目任务名与数据源 API 名称的显式路由表 (SSOT 统一注册模型)。"""

from __future__ import annotations

from stock_data.core import provider_registry as _provider_registry_module
from stock_data.core import task_aliases as _task_aliases
from stock_data.core import task_bundles as _task_bundles
from stock_data.core import task_manual_specs as _task_manual_specs
from stock_data.core.task_bundles import TaskBundle, resolve_bundle_or_alias
from stock_data.core.task_resolution import (
    TaskSpec,
    dataset_for_endpoint,
    expand_public_task_targets,
    expand_task_targets,
    get_endpoint_market,
    is_bar_task,
    is_per_symbol_task,
    is_task_partitioned,
    list_available_tasks,
    resolve_public_task,
    resolve_task,
    task_api_name,
    task_dataset,
)

_provider_registry = _provider_registry_module.provider_registry
_CUSTOM_TASKS = _task_manual_specs.CUSTOM_TASKS
_ALIASES = _task_aliases.TASK_ALIASES
_DISABLED_TASKS = _task_aliases.DISABLED_TASKS
_EXPLICIT_ONLY_TASKS = _task_aliases.EXPLICIT_ONLY_TASKS
_make_spec = _task_manual_specs.make_task_spec

list_available_bundles = _task_bundles.list_available_bundles
resolve_bundle = _task_bundles.resolve_bundle
TASK_BUNDLES = _task_bundles.TASK_BUNDLES


__all__ = [
    "TASK_BUNDLES",
    "TaskBundle",
    "TaskSpec",
    "dataset_for_endpoint",
    "expand_public_task_targets",
    "expand_task_targets",
    "get_endpoint_market",
    "is_bar_task",
    "is_per_symbol_task",
    "is_task_partitioned",
    "list_available_bundles",
    "list_available_tasks",
    "resolve_bundle",
    "resolve_bundle_or_alias",
    "resolve_public_task",
    "resolve_task",
    "task_api_name",
    "task_dataset",
]
