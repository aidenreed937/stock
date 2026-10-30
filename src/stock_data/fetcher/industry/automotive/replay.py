"""汽车产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.automotive.registry`。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import replay_entry

__all__ = ["build_automotive_replay_plan"]


def build_automotive_replay_plan() -> dict[str, dict[str, Any]]:
    """构建汽车产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.automotive.collectors.nev import NevCollector
    from stock_data.fetcher.industry.automotive.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.automotive.transform import records_to_nev_frame

    return {
        "nev_monthly_sales": replay_entry(
            "nev_monthly_sales",
            loader=lambda raw_root: NevCollector(raw_dir=raw_root).replay_cached_snapshots(),
            to_frame=records_to_nev_frame,
            primary_keys=None,
            specs=ENDPOINT_SPECS,
        ),
    }
