"""垂直产业景气指标任务注册定义。"""

from collections.abc import Callable
from typing import Any

INDUSTRY_TASK_SPECS: tuple[dict[str, object], ...] = (
    {
        "task": "semiconductor_sales",
        "api": "semiconductor_sales",
        "dataset": "semiconductor_sales",
        "qp": "industry",
        "frequency": "monthly",
        "primary_keys": ("report_month",),
        "date_columns": ("trade_date", "release_date"),
        "required_columns": ("report_month", "trade_date", "global_sales_usd"),
    },
    {
        "task": "nev_monthly_sales",
        "api": "nev_monthly_sales",
        "dataset": "nev_monthly_sales",
        "qp": "industry",
        "frequency": "monthly",
        "primary_keys": ("report_month",),
        "date_columns": ("trade_date", "release_date"),
        "required_columns": ("report_month", "trade_date", "wholesale_volume_ten_thousand"),
    },
    {
        "task": "solar_capacity",
        "api": "solar_capacity",
        "dataset": "solar_capacity",
        "qp": "industry",
        "frequency": "monthly",
        "primary_keys": ("report_month",),
        "date_columns": ("trade_date", "release_date"),
        "required_columns": ("report_month", "trade_date", "monthly_new_capacity_gw"),
    },
)


def build_industry_tasks(make_spec: Callable[..., Any]) -> dict[tuple[str, str], Any]:
    """生成 industry 垂直产业任务的 TaskSpec 字典。"""
    tasks: dict[tuple[str, str], Any] = {}
    for item in INDUSTRY_TASK_SPECS:
        task = str(item["task"])
        tasks[("industry", task)] = make_spec(
            task=task,
            prov="industry",
            api=str(item["api"]),
            dataset=str(item["dataset"]),
            qp=str(item["qp"]),
            fetch_mode="per_period",
            partitioned=False,
            is_single_sync=True,
            frequency=str(item["frequency"]),
            primary_keys=item.get("primary_keys", ()),
            date_columns=item.get("date_columns", ()),
            required_columns=item.get("required_columns", ()),
        )
    return tasks
