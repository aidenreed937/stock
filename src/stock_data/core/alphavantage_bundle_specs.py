"""Alpha Vantage 正式任务包定义。"""

from __future__ import annotations

ALPHAVANTAGE_TASK_BUNDLE_TASKS: dict[str, tuple[str, ...]] = {
    "stock_market_bundle": ("stock_daily_bar",),
    "macro_bundle": ("fx_daily",),
    "fundamental_bundle": (
        "earnings",
        "financials",
        "balance_sheet",
        "cashflow",
    ),
    "premium_fundamental_bundle": ("company_overview",),
}


__all__ = ["ALPHAVANTAGE_TASK_BUNDLE_TASKS"]
