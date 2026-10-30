"""垂直产业消费与医药任务契约。"""

from __future__ import annotations

INDUSTRY_CONSUME_TASK_SPECS: tuple[dict[str, object], ...] = (
    {
        "task": "pharma_license_out",
        "api": "pharma_license_out",
        "dataset": "pharma_license_out",
        "qp": "industry",
        "frequency": "monthly",
        "update_delay_days": 15,
        "update_time": "18:00",
        "primary_keys": ("report_month",),
        "date_columns": ("trade_date", "release_date"),
        "required_columns": ("report_month", "trade_date", "monthly_upfront_million_usd"),
    },
    {
        "task": "agriculture_pork",
        "api": "agriculture_pork",
        "dataset": "agriculture_pork",
        "qp": "industry",
        "frequency": "monthly",
        "update_delay_days": 18,
        "update_time": "18:00",
        "primary_keys": ("report_month",),
        "date_columns": ("trade_date", "release_date"),
        "required_columns": ("report_month", "trade_date", "sow_stock_million_heads"),
    },
)


__all__ = ["INDUSTRY_CONSUME_TASK_SPECS"]
