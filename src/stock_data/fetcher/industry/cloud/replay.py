"""云计算产业 RAW → Curated 离线重放计划（不触发网络采集）。

Curated/RAW 路径取自 :mod:`stock_data.fetcher.industry.cloud.registry`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.replay_support import replay_entry

__all__ = ["build_cloud_replay_plan"]


def _load_cloud_capex_from_raw(raw_root: Path) -> pl.DataFrame:
    """使用 Cloud collector 的离线入口，从 SEC/结构化 RAW 重建云 CapEx。"""
    from stock_data.fetcher.industry.cloud import CloudCapexCollector

    return CloudCapexCollector(raw_dir=raw_root).load_from_raw_snapshots()


def build_cloud_replay_plan() -> dict[str, dict[str, Any]]:
    """构建云计算产业的离线重放计划（metric -> 执行计划）。"""
    from stock_data.fetcher.industry.cloud import (
        build_cloud_capex_curated_frame,
        build_cloud_capex_raw_frame,
    )
    from stock_data.fetcher.industry.cloud.registry import ENDPOINT_SPECS

    return {
        "cloud_capex_quarterly": replay_entry(
            "cloud_capex_quarterly",
            loader=_load_cloud_capex_from_raw,
            to_frame=build_cloud_capex_curated_frame,
            raw_to_frame=build_cloud_capex_raw_frame,
            primary_keys=["report_quarter"],
            specs=ENDPOINT_SPECS,
        ),
    }
