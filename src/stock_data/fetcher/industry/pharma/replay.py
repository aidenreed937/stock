"""医药产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.pharma.registry`。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import csv_collector_loader, replay_entry

__all__ = ["build_pharma_replay_plan"]


def build_pharma_replay_plan() -> dict[str, dict[str, Any]]:
    """构建医药产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.pharma.collector import PharmaBdCollector
    from stock_data.fetcher.industry.pharma.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.pharma.transform import records_to_pharma_bd_frame

    return {
        "pharma_license_out": replay_entry(
            "pharma_license_out",
            loader=csv_collector_loader(PharmaBdCollector, "pharma/license_out_monthly.csv"),
            to_frame=records_to_pharma_bd_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
        ),
    }
