"""消费产业 RAW → Curated 离线重放计划（不触发网络采集）。

注意：``liquor_wholesale`` **未登记**在 :mod:`stock_data.fetcher.industry.consumer.registry`
（``ENDPOINT_SPECS`` 为空元组），故其 Curated 路径在此显式声明。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import raw_csv_loader, replay_entry

__all__ = ["build_consumer_replay_plan"]


def build_consumer_replay_plan() -> dict[str, dict[str, Any]]:
    """构建消费产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.consumer.parsers import load_liquor_raw_csv
    from stock_data.fetcher.industry.consumer.transforms import (
        records_to_liquor_wholesale_frame,
    )

    return {
        "liquor_wholesale": replay_entry(
            "liquor_wholesale",
            loader=raw_csv_loader(load_liquor_raw_csv, "consumer/liquor_wholesale_weekly.csv"),
            to_frame=records_to_liquor_wholesale_frame,
            primary_keys=["report_date"],
            curated="liquor_wholesale.parquet",
        ),
    }
