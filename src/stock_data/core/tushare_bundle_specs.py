"""TuShare 正式任务包定义。"""

from __future__ import annotations

TUSHARE_TASK_BUNDLE_TASKS: dict[str, tuple[str, ...]] = {
    "daily_market_bundle": (
        "stock_daily_bar",
        "index_daily_bar",
        "daily_basic",
        "adj_factor",
        "stk_limit",
        "limit_list_d",
        "suspend_d",
        "sw_daily",
        "moneyflow",
    ),
    "fund_daily_bundle": ("fund_daily", "fund_adj", "etf_share_size"),
    "fund_portfolio_bundle": ("fund_portfolio",),
    "hsgt_flow_bundle": ("moneyflow_hsgt", "hsgt_top10"),
    "financial_statement_bundle": (
        "income",
        "fina_indicator",
        "balancesheet",
        "cashflow",
    ),
    "pit_bundle": ("forecast", "express"),
    "macro_daily_bundle": ("shibor",),
    "macro_monthly_bundle": (
        "cn_cpi",
        "cn_ppi",
        "cn_pmi",
        "cn_m",
        "sf_month",
        "shibor_lpr",
        "cn_schedule",
    ),
    "metadata_bundle": (
        "stock_basic",
        "index_basic",
        "index_classify",
        "index_member",
    ),
    "corporate_action_bundle": (
        "stk_holdertrade",
        "repurchase",
        "block_trade",
        "share_float",
    ),
    "shareholder_event_bundle": (
        "dividend",
        "stk_managers",
        "stk_surv",
    ),
    "research_daily_bundle": ("cyq_perf",),
    "market_behavior_bundle": ("top_list", "top_inst", "dc_concept"),
    "pledge_bundle": ("pledge_detail", "pledge_stat"),
    "us_market_bundle": ("us_stock_daily_bar",),
}


__all__ = ["TUSHARE_TASK_BUNDLE_TASKS"]
