"""有色金属产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.metals.registry`。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import raw_csv_loader, replay_entry

__all__ = ["build_metals_replay_plan"]


def build_metals_replay_plan() -> dict[str, dict[str, Any]]:
    """构建有色金属产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.metals.parsers import load_metals_raw_csv
    from stock_data.fetcher.industry.metals.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.metals.transforms import records_to_metals_frame

    return {
        "non_ferrous_metals": replay_entry(
            "non_ferrous_metals",
            loader=raw_csv_loader(load_metals_raw_csv, "metals/commodity_prices.csv"),
            to_frame=records_to_metals_frame,
            primary_keys=["trade_date"],
            specs=ENDPOINT_SPECS,
        ),
    }
