"""数据源调度任务包定义。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskBundle:
    """一组可由调度入口展开的原子项目任务。"""

    bundle_name: str
    provider: str
    tasks: tuple[str, ...]


_TASK_BUNDLE_TASKS: dict[str, dict[str, tuple[str, ...]]] = {
    "tushare": {
        "market_bundle": (
            "stock_daily_bar",
            "daily_basic",
            "adj_factor",
            "stk_limit",
            "limit_list_d",
            "suspend_d",
        ),
        "industry_bundle": ("sw_daily",),
        "index_bundle": ("index_daily_bar", "index_dailybasic"),
        "index_weight_bundle": ("index_weight",),
        "fund_bundle": ("fund_daily", "fund_adj", "fund_share", "etf_share_size"),
        "equity_flow_bundle": ("moneyflow", "hk_hold", "margin_detail"),
        "liquidity_bundle": ("margin", "moneyflow_hsgt", "hsgt_top10"),
        "fundamental_bundle": ("income", "fina_indicator", "balancesheet", "cashflow"),
        "pit_bundle": ("forecast", "express"),
        "report_rc_bundle": ("report_rc",),
        "macro_daily_bundle": ("shibor", "cn_schedule"),
        "macro_periodic_bundle": (
            "cn_gdp",
            "cn_cpi",
            "cn_ppi",
            "cn_pmi",
            "cn_m",
            "sf_month",
            "shibor_lpr",
        ),
        "metadata_bundle": (
            "stock_basic",
            "index_basic",
            "index_classify",
            "index_member",
            "fund_basic",
            "trade_cal",
        ),
        "derivatives_bundle": ("fut_index_daily", "opt_basic", "opt_daily"),
    },
    "lixinger": {
        "market_bundle": ("stock_daily_bar", "index_daily_bar"),
        "industry_bundle": (
            "sw_2021_constituents",
            "sw_2021_fundamental",
            "sw_2021_l2_fundamental",
            "sw_2021_fs_non_financial",
            "sw_2021_fs_bank",
            "sw_2021_fs_security",
            "sw_2021_fs_insurance",
        ),
        "company_bundle": (
            "company_fundamental",
            "fs_non_financial",
            "fs_bank",
            "fs_security",
            "fs_insurance",
            "pledge_info",
        ),
        "macro_bundle": (
            "national_debt",
            "interest_rates",
            "non_ferrous_metals",
            "crude_oil",
            "investor_accounts",
            "cn_m",
            "sf_month",
        ),
        "index_bundle": ("index_fundamental",),
    },
}

TASK_BUNDLES: dict[tuple[str, str], TaskBundle] = {
    (provider, bundle_name): TaskBundle(bundle_name, provider, tasks)
    for provider, bundles in _TASK_BUNDLE_TASKS.items()
    for bundle_name, tasks in bundles.items()
}
