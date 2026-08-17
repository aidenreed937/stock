"""数据源调度任务包定义。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskBundle:
    """一组可由调度入口展开的原子项目任务。"""

    bundle_name: str
    provider: str
    tasks: tuple[str, ...]


# 正式 bundle 只收录多个调度契约一致的原子任务；单任务继续使用原子 endpoint。
_TASK_BUNDLE_TASKS: dict[str, dict[str, tuple[str, ...]]] = {
    "tushare": {
        "daily_market_bundle": (
            "daily_basic",
            "adj_factor",
            "limit_list_d",
            "sw_daily",
            "moneyflow",
        ),
        "fund_daily_bundle": ("fund_daily", "fund_adj", "etf_share_size"),
        "hsgt_flow_bundle": ("moneyflow_hsgt", "hsgt_top10"),
        "financial_statement_bundle": ("income", "fina_indicator", "balancesheet"),
        "pit_bundle": ("forecast", "express"),
        "macro_daily_bundle": ("shibor", "cn_schedule"),
        "macro_monthly_bundle": (
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
        ),
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
        "macro_daily_bundle": (
            "national_debt",
            "interest_rates",
            "non_ferrous_metals",
            "crude_oil",
        ),
        "macro_monthly_bundle": ("investor_accounts", "cn_m", "sf_month"),
    },
    "yfinance": {
        "fundamental_bundle": ("financials", "balance_sheet"),
        "corporate_action_bundle": ("dividends", "splits"),
        "research_daily_bundle": ("analyst_price_target", "fast_info"),
        "research_event_bundle": ("recommendations", "insider_transactions"),
    },
    "fred": {
        "macro_monthly_bundle": ("FEDFUNDS", "CPIAUCSL", "UNRATE", "PAYEMS"),
    },
}

# 历史 bundle 名称继续可展开，但不出现在推荐列表中。
TASK_BUNDLE_ALIASES: dict[tuple[str, str], tuple[str, ...]] = {
    ("tushare", "market_bundle"): (
        "stock_daily_bar",
        "daily_basic",
        "adj_factor",
        "stk_limit",
        "limit_list_d",
        "suspend_d",
    ),
    ("tushare", "industry_bundle"): ("sw_daily",),
    ("tushare", "index_bundle"): ("index_daily_bar", "index_dailybasic"),
    ("tushare", "index_weight_bundle"): ("index_weight",),
    ("tushare", "fund_bundle"): ("fund_daily", "fund_adj", "fund_share", "etf_share_size"),
    ("tushare", "fund_share_bundle"): ("fund_share",),
    ("tushare", "moneyflow_bundle"): ("moneyflow",),
    ("tushare", "equity_flow_bundle"): ("moneyflow", "hk_hold", "margin_detail"),
    ("tushare", "liquidity_bundle"): ("margin", "moneyflow_hsgt", "hsgt_top10"),
    ("tushare", "fundamental_bundle"): (
        "income",
        "fina_indicator",
        "balancesheet",
        "cashflow",
    ),
    ("tushare", "cashflow_bundle"): ("cashflow",),
    ("tushare", "report_rc_bundle"): ("report_rc",),
    ("tushare", "suspension_bundle"): ("suspend_d",),
    ("tushare", "fund_metadata_bundle"): ("fund_basic",),
    ("tushare", "calendar_bundle"): ("trade_cal",),
    ("tushare", "futures_bundle"): ("fut_index_daily",),
    ("tushare", "options_daily_bundle"): ("opt_daily",),
    ("tushare", "options_static_bundle"): ("opt_basic",),
    ("tushare", "derivatives_bundle"): ("fut_index_daily", "opt_basic", "opt_daily"),
    ("tushare", "macro_periodic_bundle"): (
        "cn_gdp",
        "cn_cpi",
        "cn_ppi",
        "cn_pmi",
        "cn_m",
        "sf_month",
        "shibor_lpr",
    ),
    ("lixinger", "macro_bundle"): (
        "national_debt",
        "interest_rates",
        "non_ferrous_metals",
        "crude_oil",
        "investor_accounts",
        "cn_m",
        "sf_month",
    ),
    ("lixinger", "index_bundle"): ("index_fundamental",),
    ("yfinance", "market_bundle"): ("stock_daily_bar", "index_daily_bar"),
    ("yfinance", "stock_market_bundle"): ("stock_daily_bar",),
    ("yfinance", "index_market_bundle"): ("index_daily_bar",),
    ("yfinance", "macro_bundle"): ("macro_indicators",),
    ("yfinance", "valuation_bundle"): ("index_valuation",),
    ("yfinance", "cashflow_bundle"): ("cashflow",),
    ("yfinance", "holders_bundle"): ("institutional_holders",),
    ("fred", "macro_daily_bundle"): ("T10Y2Y",),
    ("fred", "macro_quarterly_bundle"): ("GDP",),
    ("fred", "macro_weekly_bundle"): ("WALCL",),
}

TASK_BUNDLES: dict[tuple[str, str], TaskBundle] = {
    (provider, bundle_name): TaskBundle(bundle_name, provider, tasks)
    for provider, bundles in _TASK_BUNDLE_TASKS.items()
    for bundle_name, tasks in bundles.items()
}
