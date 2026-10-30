"""垂直产业项目级手工任务映射。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from stock_data.core.industry_task_specs import INDUSTRY_TASK_SPECS


def build_industry_tasks(make_spec: Callable[..., Any]) -> dict[tuple[str, str], Any]:
    """生成 industry 垂直产业任务的 TaskSpec 字典。"""
    tasks: dict[tuple[str, str], Any] = {}
    for item in INDUSTRY_TASK_SPECS:
        task = str(item["task"])
        spec = make_spec(
            task=task,
            prov="industry",
            api=str(item["api"]),
            dataset=str(item["dataset"]),
            qp=str(item["qp"]),
            fetch_mode=str(item.get("fetch_mode", "per_period")),
            partitioned=bool(item.get("partitioned", False)),
            is_single_sync=bool(item.get("is_single_sync", True)),
            frequency=str(item["frequency"]),
            primary_keys=item.get("primary_keys", ()),
            date_columns=item.get("date_columns", ()),
            required_columns=item.get("required_columns", ()),
            units=item.get("units", {}),
            update_delay_days=int(str(item.get("update_delay_days", 0))),
            update_time=str(item.get("update_time", "18:00")),
            query_mode=str(item.get("query_mode", "trade_date")),
            refresh_current_period=bool(item.get("refresh_current_period", True)),
            watermark_column=item.get("watermark_column"),
            sync_policy=str(item.get("sync_policy", "incremental")),
            max_increment_days=item.get("max_increment_days"),
        )
        tasks[("industry", task)] = spec
        dataset = str(item["dataset"])
        if dataset != task:
            tasks[("industry", dataset)] = spec
    return tasks


__all__ = ["INDUSTRY_TASK_SPECS", "build_industry_tasks"]
