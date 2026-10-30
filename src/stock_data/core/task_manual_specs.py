"""需要项目显式映射的任务注册清单。"""

from __future__ import annotations

from typing import Any

from stock_data.core.alphavantage_tasks import build_alphavantage_tasks
from stock_data.core.fred_manual_tasks import build_fred_manual_tasks
from stock_data.core.industry_tasks import build_industry_tasks
from stock_data.core.lixinger_macro_tasks import build_lixinger_macro_tasks
from stock_data.core.lixinger_manual_tasks import build_lixinger_manual_tasks
from stock_data.core.lixinger_risk_tasks import build_lixinger_risk_tasks
from stock_data.core.task_types import TaskSpec
from stock_data.core.tushare_manual_tasks import build_tushare_manual_tasks
from stock_data.core.yfinance_manual_tasks import build_yfinance_manual_tasks


def make_task_spec(
    task: str,
    prov: str,
    api: str,
    dataset: str,
    qp: str = "generic",
    fetch_mode: str = "per_day",
    partitioned: bool = True,
    is_single_sync: bool = False,
    required_pool: str | None = None,
    frequency: str = "daily",
    **kwargs: Any,
) -> TaskSpec:
    """构造手工注册任务的调度契约。"""
    return TaskSpec(
        task_name=task,
        provider=prov,
        api_name=api,
        dataset=dataset,
        frequency=frequency,
        quality_profile=qp,
        fetch_mode=fetch_mode,
        partitioned=partitioned,
        is_single_sync=is_single_sync,
        required_pool=required_pool,
        primary_keys=kwargs.get("primary_keys", ()),
        date_columns=kwargs.get("date_columns", ()),
        required_columns=kwargs.get("required_columns", ()),
        units=kwargs.get("units", {}),
        identity_renames=kwargs.get("identity_renames", {}),
        query_mode=kwargs.get("query_mode", "trade_date"),
        update_delay_days=kwargs.get("update_delay_days", 0),
        update_time=kwargs.get("update_time", "18:00"),
        delay_in_trading_days=kwargs.get("delay_in_trading_days", False),
        refresh_current_period=kwargs.get("refresh_current_period", True),
        watermark_column=kwargs.get("watermark_column"),
        sync_policy=kwargs.get("sync_policy", "incremental"),
        max_codes_per_request=kwargs.get("max_codes_per_request"),
        max_increment_days=kwargs.get("max_increment_days"),
    )


def build_custom_tasks() -> dict[tuple[str, str], TaskSpec]:
    """汇总项目级手工任务、行业任务和理杏仁补充任务。"""
    tasks: dict[tuple[str, str], TaskSpec] = {}
    tasks.update(build_tushare_manual_tasks(make_task_spec))
    tasks.update(build_yfinance_manual_tasks(make_task_spec))
    tasks.update(build_alphavantage_tasks(make_task_spec))
    tasks.update(build_fred_manual_tasks(make_task_spec))
    tasks.update(build_lixinger_manual_tasks(make_task_spec))
    tasks.update(build_industry_tasks(make_task_spec))
    tasks.update(build_lixinger_macro_tasks(make_task_spec))
    tasks.update(build_lixinger_risk_tasks(make_task_spec))
    return tasks


CUSTOM_TASKS = build_custom_tasks()


__all__ = ["CUSTOM_TASKS", "build_custom_tasks", "make_task_spec"]
