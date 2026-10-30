"""消费电子产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.electronics.registry`。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import csv_collector_loader, replay_entry

__all__ = ["build_electronics_replay_plan"]


def build_electronics_replay_plan() -> dict[str, dict[str, Any]]:
    """构建消费电子产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.electronics.collector import ConsumerElectronicsCollector
    from stock_data.fetcher.industry.electronics.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.electronics.transform import (
        records_to_consumer_electronics_frame,
    )

    return {
        "consumer_electronics": replay_entry(
            "consumer_electronics",
            loader=csv_collector_loader(
                ConsumerElectronicsCollector,
                "electronics/electronics_shipments_quarterly.csv",
            ),
            to_frame=records_to_consumer_electronics_frame,
            primary_keys=["report_quarter"],
            specs=ENDPOINT_SPECS,
        ),
    }
