"""yfinance 正式任务包定义。"""

from __future__ import annotations

YFINANCE_TASK_BUNDLE_TASKS: dict[str, tuple[str, ...]] = {
    "fundamental_bundle": ("financials", "balance_sheet"),
    "corporate_action_bundle": ("dividends", "splits"),
    "research_daily_bundle": ("analyst_price_target", "fast_info"),
    "research_event_bundle": ("recommendations", "insider_transactions"),
}


__all__ = ["YFINANCE_TASK_BUNDLE_TASKS"]
