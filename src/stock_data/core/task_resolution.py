"""项目任务解析入口。"""

from __future__ import annotations

from typing import cast

from stock_data.core.derived_datasets import resolve_derived_dataset
from stock_data.core.provider_registry import provider_registry as _provider_registry
from stock_data.core.task_aliases import TASK_ALIASES as _ALIASES
from stock_data.core.task_bundles import expand_task_targets as _expand_task_targets
from stock_data.core.task_bundles import list_available_bundles as _list_available_bundles
from stock_data.core.task_bundles import resolve_bundle as _resolve_bundle
from stock_data.core.task_catalog import list_available_tasks as _list_available_tasks
from stock_data.core.task_contracts import enrich_task_spec
from stock_data.core.task_derivation import derive_task_spec
from stock_data.core.task_manual_specs import CUSTOM_TASKS as _CUSTOM_TASKS
from stock_data.core.task_market import resolve_endpoint_market
from stock_data.core.task_name_rules import normalize_task_name
from stock_data.core.task_types import TaskSpec

list_available_bundles = _list_available_bundles
resolve_bundle = _resolve_bundle
list_available_tasks = _list_available_tasks


def expand_task_targets(provider: str, endpoints: list[str] | None = None) -> list[str]:
    """展开任务包，并保留任务注册表的别名规范化行为。"""
    if not endpoints:
        return list_available_tasks(provider)
    return _expand_task_targets(provider, endpoints, _ALIASES)


def resolve_task(provider: str, task_name: str, symbol: str = "") -> TaskSpec:
    """解析公开任务名，并返回其唯一上游 API 路由及完整调度契约。"""
    provider_name = provider.lower()
    requested = normalize_task_name(provider_name, task_name)

    custom = _CUSTOM_TASKS.get((provider_name, requested))
    if custom is not None:
        return cast("TaskSpec", enrich_task_spec(custom, _provider_registry))

    registry = _provider_registry(provider_name)
    meta = registry.get(requested)
    if meta is None:
        if "/" in requested:
            raise ValueError(
                f"未知项目任务 [{provider_name}/{task_name}]。"
                "请使用项目任务名，不要直接传入上游接口路径。"
            )
        return TaskSpec(
            task_name=requested,
            provider=provider_name,
            api_name=requested,
            dataset=requested,
        )

    return derive_task_spec(provider_name, requested, meta)


def is_per_symbol_task(provider: str, task_name: str) -> bool:
    """判断指定数据源与任务是否属于按标的代码拉取模式 (per_symbol)。"""
    try:
        return resolve_task(provider, task_name).fetch_mode == "per_symbol"
    except Exception:
        return provider.lower() in ("fred", "yfinance")


def is_task_partitioned(provider: str, task_or_dataset: str) -> bool:
    """判断指定数据源与数据集/任务是否采用 Hive 年月时间分桶存储。"""
    if resolve_derived_dataset(provider, task_or_dataset) is not None:
        return False
    try:
        return resolve_task(provider, task_or_dataset).partitioned
    except Exception:
        return provider.lower() not in ("fred", "lixinger")


def task_api_name(provider: str, task_name: str, symbol: str = "") -> str:
    """返回任务对应的真实上游 API 名称。"""
    return resolve_task(provider, task_name, symbol=symbol).api_name


def task_dataset(provider: str, task_name: str, symbol: str = "") -> str:
    """返回任务对应的唯一落盘数据集目录名。"""
    return resolve_task(provider, task_name, symbol=symbol).dataset


def is_bar_task(provider: str, task_name: str, symbol: str = "") -> bool:
    """判断任务是否使用行情 K 线清洗与契约。"""
    return resolve_task(provider, task_name, symbol=symbol).quality_profile == "bar"


def _task_api_name_for_market(provider: str, endpoint: str) -> str:
    return resolve_task(provider, endpoint).api_name


def get_endpoint_market(provider: str, endpoint: str) -> str:
    """根据项目任务名解析上游接口，再获取归属市场。"""
    return resolve_endpoint_market(provider, endpoint, _task_api_name_for_market)


def dataset_for_endpoint(endpoint: str, symbol: str = "", provider: str = "tushare") -> str:
    """返回项目任务对应的唯一数据集目录名。"""
    return task_dataset(provider, endpoint, symbol=symbol)


def resolve_public_task(provider: str, task_name: str, symbol: str = "") -> TaskSpec:
    """解析 CLI/配置公开任务名，拒绝别名、路径和未注册任务。"""
    from stock_data.core.public_tasks import resolve_public_task as _resolve_public_task

    return cast("TaskSpec", _resolve_public_task(provider, task_name, symbol))


def expand_public_task_targets(provider: str, endpoints: list[str] | None = None) -> list[str]:
    """展开公共调度入口的任务包并严格校验。"""
    from stock_data.core.public_tasks import (
        expand_public_task_targets as _expand_public_task_targets,
    )

    return _expand_public_task_targets(provider, endpoints)


__all__ = [
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
    "resolve_public_task",
    "resolve_task",
    "task_api_name",
    "task_dataset",
]
