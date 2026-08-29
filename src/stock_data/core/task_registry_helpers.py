"""任务注册表的轻量共享判定辅助函数。"""

PER_PERIOD_DATASETS: frozenset[str] = frozenset(
    {
        "income",
        "fina_indicator",
        "balancesheet",
        "cashflow",
        "fund_portfolio",
        "top10_floatholders",
        "stk_holdernumber",
    }
)
EXPLICIT_ONLY_TASKS = frozenset(
    {
        ("fred", "macro_indicators"),
        ("tushare", "fund_portfolio"),
        ("tushare", "pledge_detail"),
        ("tushare", "pledge_stat"),
        ("tushare", "stk_holdernumber"),
        ("tushare", "top10_floatholders"),
        ("tushare", "dividend"),
        ("tushare", "cyq_perf"),
        ("tushare", "cyq_chips"),
        ("tushare", "top_list"),
        ("tushare", "top_inst"),
        ("tushare", "dc_concept"),
        ("tushare", "dc_concept_cons"),
        ("tushare", "stk_managers"),
        ("tushare", "stk_surv"),
        ("lixinger", "regulatory_measures"),
        ("lixinger", "exchange_inquiry"),
        ("lixinger", "unlock_summary"),
    }
)


NON_SINGLE_SYNC_GROUPS = frozenset(
    {"financial_statements", "financial_indicator", "market_data", "fund_market", "fund_holdings"}
)
NON_SINGLE_SYNC_DATASETS = frozenset(
    {
        "income",
        "fina_indicator",
        "forecast",
        "express",
        "balancesheet",
        "cashflow",
        "fund_portfolio",
    }
)


def is_tushare_internal_api(name: str) -> bool:
    """判断名称是否为财务报表 VIP 内部接口。"""
    return name.endswith("_vip") and name.removesuffix("_vip") in PER_PERIOD_DATASETS
