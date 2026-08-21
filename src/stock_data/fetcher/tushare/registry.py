"""TuShare 接口元数据注册表模块。"""

from stock_data.fetcher.tushare.endpoints.finance import FINANCE_ENDPOINTS
from stock_data.fetcher.tushare.endpoints.market import MARKET_ENDPOINTS
from stock_data.fetcher.tushare.registry_meta import EndpointMeta

__all__ = ["TUSHARE_API_REGISTRY", "TUSHARE_TASK_REGISTRY", "EndpointMeta"]

# 汇总所有行情与财务元数据字典
TUSHARE_API_REGISTRY: dict[str, EndpointMeta] = {
    **MARKET_ENDPOINTS,
    **FINANCE_ENDPOINTS,
}

# 公开项目任务名与 TuShare API 名称分离；采集器只通过 api_name 发起请求。
TUSHARE_TASK_REGISTRY: dict[str, EndpointMeta] = {
    "stock_daily_bar": TUSHARE_API_REGISTRY["daily"],
    "stk_limit": TUSHARE_API_REGISTRY["stk_limit"],
    "limit_list_d": TUSHARE_API_REGISTRY["limit_list_d"],
    "opt_basic": TUSHARE_API_REGISTRY["opt_basic"],
    "opt_daily": TUSHARE_API_REGISTRY["opt_daily"],
    "cb_basic": TUSHARE_API_REGISTRY["cb_basic"],
    "cb_daily": TUSHARE_API_REGISTRY["cb_daily"],
    "stk_holdertrade": TUSHARE_API_REGISTRY["stk_holdertrade"],
    "repurchase": TUSHARE_API_REGISTRY["repurchase"],
    "block_trade": TUSHARE_API_REGISTRY["block_trade"],
    "share_float": TUSHARE_API_REGISTRY["share_float"],
    "income": TUSHARE_API_REGISTRY["income"],
    "fina_indicator": TUSHARE_API_REGISTRY["fina_indicator"],
    "balancesheet": TUSHARE_API_REGISTRY["balancesheet"],
    "cashflow": TUSHARE_API_REGISTRY["cashflow"],
}

# 对已注册但尚未逐项声明的接口，至少从自然键生成结构化基础契约
for _meta in TUSHARE_API_REGISTRY.values():
    if not _meta.required_columns:
        _meta.required_columns.extend(_meta.primary_keys)
    if not _meta.date_columns:
        _meta.date_columns.extend(
            key
            for key in _meta.primary_keys
            if key in {"trade_date", "end_date", "suspend_date", "month", "quarter", "date"}
        )

# 基于 TuShare 本地接口目录的业务字段 profile
_TUSHARE_PROFILES: dict[str, tuple[list[str], dict[str, str], str]] = {
    "daily": (
        ["ts_code", "trade_date", "open", "high", "low", "close"],
        {
            "open": "CNY/share",
            "high": "CNY/share",
            "low": "CNY/share",
            "close": "CNY/share",
            "vol": "share",
            "amount": "CNY",
        },
        "bar",
    ),
    "index_daily": (
        ["ts_code", "trade_date", "open", "high", "low", "close"],
        {
            "open": "point",
            "high": "point",
            "low": "point",
            "close": "point",
            "vol": "share",
            "amount": "CNY",
        },
        "bar",
    ),
    "fund_daily": (
        ["ts_code", "trade_date", "open", "high", "low", "close"],
        {
            "open": "CNY/share",
            "high": "CNY/share",
            "low": "CNY/share",
            "close": "CNY/share",
            "vol": "share",
            "amount": "CNY",
        },
        "bar",
    ),
    "daily_basic": (
        ["ts_code", "trade_date"],
        {
            "turnover_rate": "percent",
            "pe": "ratio",
            "pb": "ratio",
            "total_mv": "CNY10k",
        },
        "market_indicator",
    ),
    "stk_limit": (
        ["ts_code", "trade_date", "up_limit", "down_limit"],
        {
            "pre_close": "CNY/share",
            "up_limit": "CNY/share",
            "down_limit": "CNY/share",
        },
        "market_indicator",
    ),
    "limit_list_d": (
        ["ts_code", "trade_date", "limit"],
        {
            "close": "CNY/share",
            "pct_chg": "percent",
            "amount": "CNY",
            "limit_amount": "CNY",
            "float_mv": "CNY",
            "total_mv": "CNY",
            "turnover_ratio": "percent",
            "fd_amount": "CNY",
            "open_times": "count",
            "limit_times": "count",
        },
        "event",
    ),
    "index_dailybasic": (
        ["ts_code", "trade_date"],
        {"pe": "ratio", "pb": "ratio", "turnover_rate": "percent"},
        "market_indicator",
    ),
    "adj_factor": (
        ["ts_code", "trade_date", "adj_factor"],
        {"adj_factor": "factor"},
        "corporate_action",
    ),
    "income": (
        ["ts_code", "end_date", "report_type"],
        {"revenue": "CNY", "n_income": "CNY"},
        "financial_statement",
    ),
    "fina_indicator": (
        ["ts_code", "end_date"],
        {
            "roe": "percent",
            "grossprofit_margin": "percent",
            "netprofit_margin": "percent",
        },
        "financial_indicator",
    ),
    "suspend_d": (["ts_code", "trade_date"], {}, "event"),
    "index_weight": (
        ["index_code", "con_code", "trade_date", "weight"],
        {"weight": "percent"},
        "constituent_weight",
    ),
    "margin": (
        ["trade_date", "exchange_id"],
        {"rzye": "CNY10k", "rqye": "CNY10k"},
        "margin_summary",
    ),
    "margin_detail": (
        ["ts_code", "trade_date"],
        {"rzye": "CNY10k", "rqye": "CNY10k"},
        "margin_detail",
    ),
    "moneyflow_hsgt": (
        ["trade_date"],
        {
            "ggt_ss": "CNY1m",
            "ggt_sz": "CNY1m",
            "hgt": "CNY1m",
            "sgt": "CNY1m",
            "north_money": "CNY1m",
            "south_money": "CNY1m",
        },
        "northbound_flow",
    ),
    "hsgt_top10": (
        ["trade_date", "ts_code", "market_type"],
        {"buy_amount": "CNY10k", "sell_amount": "CNY10k"},
        "northbound_top10",
    ),
    "fund_basic": (["ts_code", "name", "fund_type"], {}, "static"),
    "fund_share": (
        ["ts_code", "trade_date", "fd_share"],
        {"fd_share": "share"},
        "fund_share",
    ),
    "etf_share_size": (
        ["ts_code", "trade_date", "total_share"],
        {"total_share": "share"},
        "fund_share",
    ),
    "sw_daily": (
        ["ts_code", "trade_date", "open", "high", "low", "close"],
        {"close": "point", "vol": "share", "amount": "CNY"},
        "bar",
    ),
    "cn_gdp": (
        ["quarter"],
        {"gdp": "CNY100m", "gdp_yoy": "percent"},
        "macro_quarterly",
    ),
    "cn_cpi": (
        ["month"],
        {"nt_val": "index", "nt_yoy": "percent"},
        "macro_monthly",
    ),
    "cn_ppi": (
        ["month"],
        {"ppi": "index", "ppi_yoy": "percent"},
        "macro_monthly",
    ),
    "cn_pmi": (["month"], {"pmi": "index"}, "macro_monthly"),
    "cn_m": (
        ["month"],
        {"m0": "CNY100m", "m1": "CNY100m", "m2": "CNY100m"},
        "macro_monthly",
    ),
    "sf_month": (["month"], {"social_financing": "CNY100m"}, "macro_monthly"),
    "shibor": (
        ["date"],
        {"on": "percent", "1w": "percent", "1m": "percent", "1y": "percent"},
        "macro_rate",
    ),
    "shibor_lpr": (["date"], {"1y": "percent", "5y": "percent"}, "macro_rate"),
    "cn_schedule": (["publish_date", "title"], {}, "event"),
    "fut_index_daily": (
        ["ts_code", "trade_date", "open", "high", "low", "close"],
        {"close": "point", "vol": "share", "amount": "CNY"},
        "bar",
    ),
    "opt_basic": (
        ["ts_code", "exchange", "name"],
        {"exercise_price": "CNY/contract", "list_price": "CNY/contract"},
        "static",
    ),
    "opt_daily": (
        ["ts_code", "trade_date", "close", "settle"],
        {
            "pre_settle": "CNY/contract",
            "pre_close": "CNY/contract",
            "open": "CNY/contract",
            "high": "CNY/contract",
            "low": "CNY/contract",
            "close": "CNY/contract",
            "settle": "CNY/contract",
            "vol": "contract",
            "amount": "CNY10k",
            "oi": "contract",
        },
        "options_daily",
    ),
    "cb_basic": (
        ["ts_code", "bond_short_name", "stk_code", "list_date", "exchange"],
        {
            "par": "CNY/bond",
            "issue_price": "CNY/bond",
            "issue_size": "CNY",
            "remain_size": "CNY",
            "coupon_rate": "percent",
            "add_rate": "percent",
            "first_conv_price": "CNY/share",
            "conv_price": "CNY/share",
        },
        "bond_static",
    ),
    "cb_daily": (
        ["ts_code", "trade_date", "close"],
        {
            "pre_close": "CNY/bond",
            "open": "CNY/bond",
            "high": "CNY/bond",
            "low": "CNY/bond",
            "close": "CNY/bond",
            "change": "CNY/bond",
            "pct_chg": "percent",
            "vol": "hand",
            "amount": "CNY10k",
            "bond_value": "CNY/bond",
            "bond_over_rate": "percent",
            "cb_value": "CNY/bond",
            "cb_over_rate": "percent",
        },
        "bond_daily",
    ),
    "stk_holdertrade": (
        ["ts_code", "ann_date", "holder_name", "in_de", "change_vol"],
        {
            "change_vol": "share",
            "change_ratio": "percent",
            "after_share": "share",
            "after_ratio": "percent",
            "avg_price": "CNY/share",
            "total_share": "share",
        },
        "corporate_action_event",
    ),
    "repurchase": (
        ["ts_code", "ann_date", "proc"],
        {
            "vol": "share",
            "amount": "CNY",
            "high_limit": "CNY/share",
            "low_limit": "CNY/share",
        },
        "corporate_action_event",
    ),
    "block_trade": (
        ["ts_code", "trade_date", "price", "vol", "amount"],
        {"price": "CNY/share", "vol": "10k_share", "amount": "CNY10k"},
        "corporate_action_event",
    ),
    "share_float": (
        ["ts_code", "ann_date", "float_date", "float_share", "float_ratio"],
        {"float_share": "share", "float_ratio": "percent"},
        "corporate_action_event",
    ),
    "stk_account": (
        ["date"],
        {
            "weekly_new": "10k_account",
            "total": "10k_account",
            "weekly_hold": "10k_account",
            "weekly_trade": "10k_account",
        },
        "macro_weekly",
    ),
    "forecast": (["ts_code", "ann_date", "end_date"], {}, "financial_indicator"),
    "express": (
        ["ts_code", "ann_date", "end_date"],
        {"revenue": "CNY", "n_income": "CNY"},
        "financial_statement",
    ),
    "balancesheet": (
        ["ts_code", "ann_date", "end_date"],
        {"total_assets": "CNY"},
        "financial_statement",
    ),
    "cashflow": (
        ["ts_code", "ann_date", "end_date"],
        {"n_cashflow_act": "CNY"},
        "financial_statement",
    ),
    "report_rc": (
        ["ts_code", "report_date", "org_name"],
        {"predict_net_profit": "CNY10k", "predict_eps": "CNY/share"},
        "financial_indicator",
    ),
    "index_member": (["index_code", "con_code", "in_date"], {}, "constituent_weight"),
    "index_classify": (["index_code", "industry_name"], {}, "static"),
    "trade_cal": (["exchange", "cal_date", "is_open"], {}, "static"),
}

for _endpoint, (_required, _units, _profile) in _TUSHARE_PROFILES.items():
    if _endpoint in TUSHARE_API_REGISTRY:
        _meta = TUSHARE_API_REGISTRY[_endpoint]
        _meta.required_columns[:] = _required
        _meta.units.update(_units)
        object.__setattr__(_meta, "quality_profile", _profile)
