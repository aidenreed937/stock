"""TuShare 接口元数据注册表模块。"""

from stock.data.fetcher.tushare.endpoints.finance import FINANCE_ENDPOINTS
from stock.data.fetcher.tushare.endpoints.market import MARKET_ENDPOINTS
from stock.data.fetcher.tushare.registry_meta import EndpointMeta

__all__ = ["EndpointMeta", "TUSHARE_API_REGISTRY", "TUSHARE_TASK_REGISTRY"]

# 汇总所有行情与财务元数据字典
TUSHARE_API_REGISTRY: dict[str, EndpointMeta] = {
    **MARKET_ENDPOINTS,
    **FINANCE_ENDPOINTS,
}

# 公开项目任务名与 TuShare API 名称分离；采集器只通过 api_name 发起请求。
TUSHARE_TASK_REGISTRY: dict[str, EndpointMeta] = {
    "stock_daily_bar": TUSHARE_API_REGISTRY["daily"],
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
    "shibor": (["date"], {"on": "percent", "1w": "percent", "1m": "percent", "1y": "percent"}, "macro_rate"),
    "shibor_lpr": (["date"], {"1y": "percent", "5y": "percent"}, "macro_rate"),
    "cn_schedule": (["publish_date", "title"], {}, "event"),
    "fut_index_daily": (
        ["ts_code", "trade_date", "open", "high", "low", "close"],
        {"close": "point", "vol": "share", "amount": "CNY"},
        "bar",
    ),
    "forecast": (["ts_code", "ann_date", "end_date"], {}, "financial_indicator"),
    "express": (["ts_code", "ann_date", "end_date"], {"revenue": "CNY", "n_income": "CNY"}, "financial_statement"),
    "balancesheet": (["ts_code", "ann_date", "end_date"], {"total_assets": "CNY"}, "financial_statement"),
    "cashflow": (["ts_code", "ann_date", "end_date"], {"n_cashflow_act": "CNY"}, "financial_statement"),
    "report_rc": (["ts_code", "report_date", "org_name"], {"predict_net_profit": "CNY10k", "predict_eps": "CNY/share"}, "financial_indicator"),
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
