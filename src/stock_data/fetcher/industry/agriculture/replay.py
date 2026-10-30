"""农业产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.agriculture.registry`。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import raw_csv_loader, replay_entry

__all__ = ["build_agriculture_replay_plan"]


def build_agriculture_replay_plan() -> dict[str, dict[str, Any]]:
    """构建农业产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.agriculture.parsers import load_pork_raw_csv
    from stock_data.fetcher.industry.agriculture.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.agriculture.transforms import (
        records_to_agriculture_pork_frame,
    )

    return {
        "agriculture_pork": replay_entry(
            "agriculture_pork",
            loader=raw_csv_loader(load_pork_raw_csv, "agriculture/pork_capacity_monthly.csv"),
            to_frame=records_to_agriculture_pork_frame,
            primary_keys=["report_month"],
            specs=ENDPOINT_SPECS,
        ),
    }
