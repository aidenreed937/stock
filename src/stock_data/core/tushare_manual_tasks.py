"""TuShare 项目级手工任务映射。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MakeTaskSpec = Callable[..., Any]


def build_tushare_manual_tasks(make_spec: MakeTaskSpec) -> dict[tuple[str, str], Any]:
    """生成 TuShare 需要项目短任务名或显式调度契约的任务。"""
    return {
        ("tushare", "stock_daily_bar"): make_spec(
            "stock_daily_bar",
            "tushare",
            "daily",
            "stock_daily_bar",
            "bar",
            fetch_mode="per_day",
            partitioned=True,
        ),
        ("tushare", "us_stock_daily_bar"): make_spec(
            "us_stock_daily_bar",
            "tushare",
            "us_daily",
            "stock_daily_bar",
            "bar",
            fetch_mode="per_symbol",
            partitioned=True,
        ),
        ("tushare", "hk_hold"): make_spec(
            "hk_hold", "tushare", "hk_hold", "hk_hold", fetch_mode="per_day", partitioned=True
        ),
        ("tushare", "report_rc"): make_spec(
            "report_rc", "tushare", "report_rc", "report_rc", fetch_mode="per_day", partitioned=True
        ),
        ("tushare", "forecast"): make_spec(
            "forecast",
            "tushare",
            "forecast",
            "forecast",
            fetch_mode="per_day",
            partitioned=True,
            frequency="quarterly",
        ),
        ("tushare", "express"): make_spec(
            "express",
            "tushare",
            "express",
            "express",
            fetch_mode="per_day",
            partitioned=True,
            frequency="quarterly",
        ),
        ("tushare", "index_daily_bar"): make_spec(
            "index_daily_bar",
            "tushare",
            "index_daily",
            "index_daily_bar",
            "bar",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
        ),
    }


__all__ = ["build_tushare_manual_tasks"]
