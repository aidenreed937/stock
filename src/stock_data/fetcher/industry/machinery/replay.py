"""机械产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.machinery.registry`。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import csv_collector_loader, replay_entry

__all__ = ["build_machinery_replay_plan"]


def build_machinery_replay_plan() -> dict[str, dict[str, Any]]:
    """构建机械产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.machinery.collector import MachineryCollector
    from stock_data.fetcher.industry.machinery.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.machinery.transform import records_to_machinery_frame

    return {
        "construction_machinery": replay_entry(
            "construction_machinery",
            loader=csv_collector_loader(MachineryCollector, "machinery/excavator_monthly.csv"),
            to_frame=records_to_machinery_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
        ),
    }
