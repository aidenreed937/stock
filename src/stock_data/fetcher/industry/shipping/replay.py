"""航运产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.shipping.registry`。
"""

from __future__ import annotations

from typing import Any

from stock_data.fetcher.industry.replay_support import raw_csv_loader, replay_entry

__all__ = ["build_shipping_replay_plan"]


def build_shipping_replay_plan() -> dict[str, dict[str, Any]]:
    """构建航运产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.shipping.parsers import load_shipping_raw_records
    from stock_data.fetcher.industry.shipping.registry import ENDPOINT_SPECS
    from stock_data.fetcher.industry.shipping.transforms import records_to_shipping_frame

    return {
        "shipping_indices": replay_entry(
            "shipping_indices",
            loader=raw_csv_loader(load_shipping_raw_records, "shipping/freight_indices_real.csv"),
            to_frame=records_to_shipping_frame,
            primary_keys=["trade_date"],
            specs=ENDPOINT_SPECS,
        ),
    }
