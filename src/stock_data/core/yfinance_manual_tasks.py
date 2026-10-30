"""yfinance 项目级手工任务映射。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MakeTaskSpec = Callable[..., Any]


def build_yfinance_manual_tasks(make_spec: MakeTaskSpec) -> dict[tuple[str, str], Any]:
    """生成 yfinance 需要项目短任务名或显式调度契约的任务。"""
    return {
        ("yfinance", "stock_daily_bar"): make_spec(
            "stock_daily_bar",
            "yfinance",
            "history",
            "stock_daily_bar",
            "bar",
            fetch_mode="per_symbol",
            partitioned=True,
        ),
        ("yfinance", "index_daily_bar"): make_spec(
            "index_daily_bar",
            "yfinance",
            "history",
            "index_daily_bar",
            "bar",
            fetch_mode="per_symbol",
            partitioned=False,
        ),
    }


__all__ = ["build_yfinance_manual_tasks"]
