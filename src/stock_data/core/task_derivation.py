"""从 Provider 元数据推导统一 TaskSpec。"""

from __future__ import annotations

from typing import Any

from stock_data.core.task_contracts import contract_fields
from stock_data.core.task_types import TaskSpec

_NON_SINGLE_SYNC_GROUPS = frozenset(
    {"financial_statements", "financial_indicator", "market_data", "fund_market", "fund_holdings"}
)


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _resolve_fetch_mode(meta: Any) -> str:
    fetch_mode = _optional_str(getattr(meta, "fetch_mode", None))
    return fetch_mode or "per_day"


def _resolve_partitioned(meta: Any, group: str, frequency: str) -> bool:
    partitioned = getattr(meta, "partitioned", None)
    if partitioned is not None:
        return bool(partitioned)
    return not (group in ("macro_data", "basic_info") or frequency in ("static", "event"))


def _resolve_single_sync(meta: Any, group: str, frequency: str) -> bool:
    is_single_sync = getattr(meta, "is_single_sync", None)
    if is_single_sync is not None:
        return bool(is_single_sync)
    return bool(
        group in ("macro_data", "basic_info")
        or (
            frequency in ("monthly", "quarterly", "event", "static")
            and group not in _NON_SINGLE_SYNC_GROUPS
        )
    )


def derive_task_spec(provider_name: str, requested: str, meta: Any) -> TaskSpec:
    """根据 Provider 原生元数据推导完整调度与存储契约。"""
    raw_api_name = getattr(meta, "api_name", None) or getattr(meta, "series_id", requested)
    api_name = str(raw_api_name)
    group = str(getattr(meta, "group", ""))
    frequency = str(getattr(meta, "frequency", "daily"))
    quality_profile = str(getattr(meta, "quality_profile", "generic"))
    dataset = str(getattr(meta, "dataset", None) or requested)

    return TaskSpec(
        task_name=requested,
        provider=provider_name,
        api_name=api_name,
        dataset=dataset,
        frequency=frequency,
        quality_profile=quality_profile,
        fetch_mode=_resolve_fetch_mode(meta),
        partitioned=_resolve_partitioned(meta, group, frequency),
        is_single_sync=_resolve_single_sync(meta, group, frequency),
        required_pool=_optional_str(getattr(meta, "required_pool", None)),
        **contract_fields(meta),
    )


__all__ = ["derive_task_spec"]
