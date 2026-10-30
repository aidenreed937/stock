"""任务名规范化与入口保护规则。"""

from __future__ import annotations

from stock_data.core.task_aliases import DISABLED_TASKS, TASK_ALIASES
from stock_data.core.task_bundles import resolve_bundle_or_alias
from stock_data.core.tushare_internal_apis import is_tushare_internal_api


def normalize_task_name(provider: str, task_name: str) -> str:
    """校验任务名并应用兼容别名。"""
    provider_name = provider.lower()
    requested = task_name.strip()
    if provider_name == "tushare" and is_tushare_internal_api(requested):
        raise ValueError(
            f"[{provider_name}/{task_name}] 是上游内部 API；请使用项目任务名"
            f" [{requested.removesuffix('_vip')}]。"
        )
    if requested in DISABLED_TASKS:
        raise ValueError(f"项目任务 [{provider_name}/{task_name}] 已停用；请使用 stock_daily_bar。")
    if resolve_bundle_or_alias(provider_name, requested) is not None:
        raise ValueError(
            f"[{provider_name}/{task_name}] 是任务包，不是原子任务；"
            "请先通过 expand_task_targets 展开。"
        )
    return TASK_ALIASES.get((provider_name, requested), requested)


__all__ = ["normalize_task_name"]
