"""项目任务名的兼容别名、停用清单与公开可见性。"""

from __future__ import annotations

TASK_ALIASES: dict[tuple[str, str], str] = {
    ("tushare", "daily"): "stock_daily_bar",
    ("tushare", "daily_bar"): "stock_daily_bar",
    ("tushare", "index_daily"): "index_daily_bar",
    ("yfinance", "history"): "stock_daily_bar",
    ("alphavantage", "FX_DAILY"): "fx_daily",
    ("alphavantage", "TIME_SERIES_DAILY"): "stock_daily_bar",
    ("alphavantage", "macro_indicators"): "fx_daily",
    ("fred", "history"): "macro_indicators",
    ("lixinger", "cn/company/candlestick"): "stock_daily_bar",
    ("lixinger", "cn/index/candlestick"): "index_daily_bar",
    ("lixinger", "cn/company/fundamental/non_financial"): "company_fundamental",
    ("lixinger", "cn/index/fundamental"): "index_fundamental",
    ("lixinger", "cn/industry/fundamental/sw_2021"): "sw_2021_fundamental",
    ("lixinger", "cn/industry/constituents/sw_2021"): "sw_2021_constituents",
    ("lixinger", "cn/company/fs/non_financial"): "fs_non_financial",
    ("lixinger", "cn/company/hot/ple"): "pledge_info",
    ("lixinger", "cn/fund/shareholders-structure"): "fund_holder_structure",
    ("lixinger", "macro/national-debt"): "national_debt",
    ("lixinger", "macro/interest-rates"): "interest_rates",
    ("lixinger", "macro/non-ferrous-metals"): "non_ferrous_metals",
    ("lixinger", "macro/crude-oil"): "crude_oil",
    ("lixinger", "macro/gold-price"): "gold_price",
    ("lixinger", "macro/investor"): "investor_accounts",
    ("lixinger", "macro/money-supply"): "cn_m",
    ("lixinger", "macro/social-financing"): "sf_month",
    ("lixinger", "macro/energy"): "energy",
    ("lixinger", "macro/price-index"): "price_index",
}

DISABLED_TASKS = {"bak_daily", "stk_account", "fund_basic"}
EXPLICIT_ONLY_TASKS = frozenset(
    {
        ("fred", "macro_indicators"),
        ("yfinance", "macro_indicators"),
        ("tushare", "fund_portfolio"),
        ("tushare", "fina_mainbz"),
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
        ("tushare", "us_daily"),
        ("tushare", "fut_index_daily"),
        ("lixinger", "regulatory_measures"),
        ("lixinger", "exchange_inquiry"),
        ("lixinger", "unlock_summary"),
        ("industry", "gacc_trade"),
        ("industry", "customs_trade"),
        ("industry", "chemical_spreads"),
        ("industry", "chemical_capacity_utilization_10y"),
        ("industry", "semiconductor_equipment_gm"),
        ("industry", "semiconductor_equipment_gm_multi"),
        ("industry", "semiconductor_equipment_gm_amat"),
        ("industry", "semiconductor_equipment_gm_lrcx"),
        ("industry", "semiconductor_equipment_gm_klac"),
        ("industry", "tel_gm_quarterly"),
        ("alphavantage", "company_overview"),
        ("alphavantage", "OVERVIEW"),
        ("alphavantage", "earnings"),
        ("alphavantage", "EARNINGS"),
        ("alphavantage", "financials"),
        ("alphavantage", "INCOME_STATEMENT"),
        ("alphavantage", "balance_sheet"),
        ("alphavantage", "BALANCE_SHEET"),
        ("alphavantage", "cashflow"),
        ("alphavantage", "CASH_FLOW"),
    }
)

LEGACY_ONLY_TASKS = frozenset({("industry", "customs_trade")})


__all__ = ["DISABLED_TASKS", "EXPLICIT_ONLY_TASKS", "LEGACY_ONLY_TASKS", "TASK_ALIASES"]
