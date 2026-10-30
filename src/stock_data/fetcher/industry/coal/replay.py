"""煤炭产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.coal.registry`。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import raw_csv_loader, replay_entry

__all__ = ["build_coal_replay_plan"]


def build_coal_replay_plan() -> dict[str, dict[str, Any]]:
    """构建煤炭产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.coal.parsers import load_coal_raw_csv
    from stock_data.fetcher.industry.coal.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.coal.transforms import records_to_coal_market_frame

    return {
        "coal_market": replay_entry(
            "coal_market",
            loader=raw_csv_loader(load_coal_raw_csv, "coal/coal_market_weekly.csv"),
            to_frame=records_to_coal_market_frame,
            primary_keys=["report_date"],
            specs=ENDPOINT_SPECS,
        ),
    }
