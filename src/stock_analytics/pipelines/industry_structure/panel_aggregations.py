"""行业结构面板聚合兼容门面。"""

from __future__ import annotations

from stock_analytics.pipelines.industry_structure.panel_fundamental import (
    FastFundamentalContext,
    fast_fundamental_panel,
)
from stock_analytics.pipelines.industry_structure.panel_moneyflow import (
    IndustryMoneyflowContext,
    industry_moneyflow_panel,
)

__all__ = [
    "FastFundamentalContext",
    "IndustryMoneyflowContext",
    "fast_fundamental_panel",
    "industry_moneyflow_panel",
]
