"""任务注册表的接口契约字段补全辅助函数。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

PARTITIONED_EVENT_TASKS: frozenset[str] = frozenset(
    {"stk_holdertrade", "repurchase", "block_trade", "share_float"}
)


def normalize_units(value: Any) -> dict[str, str]:
    """将不同 Provider 的单位描述收敛为统一的字段映射。"""
    if isinstance(value, dict):
        return {str(key): str(unit) for key, unit in value.items()}
    if value is None:
        return {}
    return {"value": str(value)}


def contract_fields(meta: Any, defaults: Any | None = None) -> dict[str, Any]:
    """从 Provider 元数据生成 TaskSpec 的接口契约字段。"""
    return {
        "primary_keys": tuple(getattr(meta, "primary_keys", ()) or ()),
        "date_columns": tuple(getattr(meta, "date_columns", ()) or ()),
        "required_columns": tuple(getattr(meta, "required_columns", ()) or ()),
        "units": normalize_units(getattr(meta, "units", None)),
        "query_mode": str(
            getattr(meta, "query_mode", getattr(defaults, "query_mode", "trade_date"))
        ),
        "update_time": str(getattr(meta, "update_time", getattr(defaults, "update_time", "18:00"))),
        "update_delay_days": int(
            getattr(meta, "update_delay_days", getattr(defaults, "update_delay_days", 0)) or 0
        ),
        "delay_in_trading_days": bool(
            getattr(
                meta, "delay_in_trading_days", getattr(defaults, "delay_in_trading_days", False)
            )
        ),
        "request_window_days": getattr(meta, "request_window_days", None),
        "max_rows_per_request": getattr(meta, "max_rows_per_request", None),
        "request_fields": getattr(meta, "request_fields", None),
    }


def enrich_task_spec(spec: Any, provider_registry: Callable[[str], dict[str, Any]]) -> Any:
    """将手工兼容路由补齐为与 Provider 元数据一致的接口契约。"""
    try:
        meta = provider_registry(spec.provider).get(spec.api_name)
    except Exception:
        meta = None
    if meta is None:
        return spec
    return replace(spec, **contract_fields(meta, defaults=spec))


__all__ = ["PARTITIONED_EVENT_TASKS", "contract_fields", "enrich_task_spec", "normalize_units"]
