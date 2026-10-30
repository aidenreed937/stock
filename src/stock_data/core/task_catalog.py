"""公开任务目录枚举。"""

from __future__ import annotations

from stock_data.core.provider_registry import provider_registry
from stock_data.core.task_aliases import DISABLED_TASKS, EXPLICIT_ONLY_TASKS, TASK_ALIASES
from stock_data.core.task_manual_specs import CUSTOM_TASKS
from stock_data.core.tushare_internal_apis import is_tushare_internal_api


def list_available_tasks(provider: str) -> list[str]:
    """返回指定数据源下所有已注册且未停用的公开任务名称列表。"""
    provider_name = provider.lower()
    tasks: list[str] = []
    alias_names = {
        alias for alias_provider, alias in TASK_ALIASES if alias_provider == provider_name
    }

    for (custom_provider, task_name), task_spec in CUSTOM_TASKS.items():
        if (
            custom_provider == provider_name
            and task_spec.task_name == task_name
            and (custom_provider, task_name) not in EXPLICIT_ONLY_TASKS
            and task_name not in DISABLED_TASKS
            and task_name not in alias_names
            and task_name not in tasks
        ):
            tasks.append(task_name)

    registry = provider_registry(provider_name)
    for name in registry:
        if (
            not is_tushare_internal_api(name)
            and name not in DISABLED_TASKS
            and (provider_name, name) not in EXPLICIT_ONLY_TASKS
            and name not in alias_names
            and name not in tasks
            and "/" not in name
        ):
            tasks.append(name)

    return tasks


__all__ = ["list_available_tasks"]
