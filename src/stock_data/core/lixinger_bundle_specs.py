"""理杏仁正式任务包定义。"""

from __future__ import annotations

LIXINGER_TASK_BUNDLE_TASKS: dict[str, tuple[str, ...]] = {
    "market_bundle": ("stock_daily_bar", "index_daily_bar"),
    "industry_bundle": (
        "sw_2021_constituents",
        "sw_2021_fundamental",
        "sw_2021_l2_fundamental",
    ),
    "industry_financial_bundle": (
        "sw_2021_fs_non_financial",
        "sw_2021_fs_bank",
        "sw_2021_fs_security",
        "sw_2021_fs_insurance",
        "sw_2021_l2_fs_non_financial",
        "sw_2021_l2_fs_bank",
        "sw_2021_l2_fs_security",
        "sw_2021_l2_fs_insurance",
        "sw_2021_l3_fs_non_financial",
        "sw_2021_l3_fs_bank",
        "sw_2021_l3_fs_security",
        "sw_2021_l3_fs_insurance",
    ),
    "company_bundle": (
        "company_fundamental",
        "fs_non_financial",
        "fs_bank",
        "fs_security",
        "fs_insurance",
        "pledge_info",
    ),
    "company_risk_event_bundle": ("regulatory_measures", "exchange_inquiry"),
    "macro_daily_bundle": (
        "national_debt",
        "interest_rates",
        "non_ferrous_metals",
        "crude_oil",
        "gold_price",
    ),
    "macro_monthly_bundle": (
        "investor_accounts",
        "cn_m",
        "sf_month",
        "energy",
        "price_index",
    ),
}


__all__ = ["LIXINGER_TASK_BUNDLE_TASKS"]
