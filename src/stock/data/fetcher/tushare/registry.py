"""TuShare 接口元数据注册表模块。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EndpointMeta:
    """TuShare 接口元数据描述。"""

    api_name: str
    description: str
    market: str = "CN"
    frequency: str = "daily"  # daily, monthly, quarterly, event
    group: str = "market_data"
    primary_keys: list[str] = field(default_factory=list)
    rate_limit_per_min: int = 180
    update_time: str = "18:00"
    update_delay_days: int = 0
    date_columns: list[str] = field(default_factory=list)
    required_columns: list[str] = field(default_factory=list)
    units: dict[str, str] = field(default_factory=dict)
    max_range_days: int | None = None
    request_window_days: int | None = None
    pagination_required: bool = True
    max_rows_per_request: int | None = None
    quality_profile: str = "generic"


# 常用 TuShare 接口元数据注册表 (全局统一由 TuShareClient / data.yaml 控制限频)
TUSHARE_API_REGISTRY: dict[str, EndpointMeta] = {
    "daily": EndpointMeta(
        api_name="daily",
        description="A 股日线行情",
        frequency="daily",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        update_time="17:00",
        update_delay_days=0,
        date_columns=["trade_date"], required_columns=["ts_code", "trade_date", "open", "high", "low", "close"],
    ),
    "daily_basic": EndpointMeta(
        api_name="daily_basic",
        description="每日指标（换手率、PE、PB、总市值等）",
        frequency="daily",
        group="market_indicators",
        primary_keys=["ts_code", "trade_date"],
        update_time="18:00",
        update_delay_days=0,
        date_columns=["trade_date"], required_columns=["ts_code", "trade_date"], max_rows_per_request=6000,
    ),
    "stock_basic": EndpointMeta(
        api_name="stock_basic",
        description="基础股票列表",
        frequency="event",
        group="basic_info",
        primary_keys=["ts_code"],
        required_columns=["ts_code"], pagination_required=True,
    ),
    "adj_factor": EndpointMeta(
        api_name="adj_factor",
        description="复权因子数据",
        frequency="daily",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        date_columns=["trade_date"], required_columns=["ts_code", "trade_date"],
    ),
    "income": EndpointMeta(
        api_name="income",
        description="上市公司利润表",
        frequency="quarterly",
        group="financial_statements",
        primary_keys=["ts_code", "end_date"],
        date_columns=["end_date"], required_columns=["ts_code", "end_date"],
    ),
    "index_daily": EndpointMeta(
        api_name="index_daily",
        description="指数日线行情",
        frequency="daily",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        date_columns=["trade_date"], required_columns=["ts_code", "trade_date", "open", "high", "low", "close"], max_rows_per_request=8000,
    ),
    "suspend_d": EndpointMeta(
        api_name="suspend_d",
        description="每日停复牌信息",
        frequency="daily",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["ts_code", "trade_date"],
    ),
    "fina_indicator": EndpointMeta(
        api_name="fina_indicator",
        description="财务指标数据（ROE/毛利率等）",
        frequency="quarterly",
        group="financial_statements",
        primary_keys=["ts_code", "end_date"],
        date_columns=["end_date"],
        required_columns=["ts_code", "end_date"],
    ),
    "moneyflow": EndpointMeta(
        api_name="moneyflow",
        description="个股资金流向",
        frequency="daily",
        group="money_flow",
        primary_keys=["ts_code", "trade_date"],
    ),
    "hk_hold": EndpointMeta(
        api_name="hk_hold",
        description="沪深港通持股明细（北向资金）",
        frequency="daily",
        group="money_flow",
        primary_keys=["ts_code", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["ts_code", "trade_date"],
    ),
    "index_basic": EndpointMeta(
        api_name="index_basic",
        description="指数基本信息",
        frequency="event",
        group="basic_info",
        primary_keys=["ts_code"],
    ),
    "index_dailybasic": EndpointMeta(
        api_name="index_dailybasic",
        description="指数每日估值与指标",
        frequency="daily",
        group="market_indicators",
        primary_keys=["ts_code", "trade_date"],
    ),
    "index_weight": EndpointMeta(
        api_name="index_weight",
        description="指数成分股权重",
        frequency="monthly",
        group="basic_info",
        primary_keys=["index_code", "con_code", "trade_date"],
    ),
    "index_classify": EndpointMeta(
        api_name="index_classify",
        description="申万行业分类",
        frequency="event",
        group="basic_info",
        primary_keys=["index_code"],
    ),
    "index_member": EndpointMeta(
        api_name="index_member",
        description="申万行业成分股",
        frequency="event",
        group="basic_info",
        primary_keys=["index_code", "con_code", "in_date", "out_date"],
        required_columns=["index_code", "con_code", "in_date", "out_date"],
    ),
    "sw_daily": EndpointMeta(
        api_name="sw_daily",
        description="申万行业日线行情",
        frequency="daily",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
    ),
    "margin": EndpointMeta(
        api_name="margin",
        description="融资融券交易汇总",
        frequency="daily",
        group="market_indicators",
        primary_keys=["trade_date", "exchange_id"],
        update_time="09:00",
        update_delay_days=1,
    ),
    "margin_detail": EndpointMeta(
        api_name="margin_detail",
        description="融资融券交易明细",
        frequency="daily",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["ts_code", "trade_date"],
        update_time="09:00",
        update_delay_days=1,
    ),
    "moneyflow_hsgt": EndpointMeta(
        api_name="moneyflow_hsgt",
        description="沪深港通资金流向",
        frequency="daily",
        group="money_flow",
        primary_keys=["trade_date"],
    ),
    "hsgt_top10": EndpointMeta(
        api_name="hsgt_top10",
        description="沪深港通十大成交股",
        frequency="daily",
        group="money_flow",
        primary_keys=["trade_date", "ts_code", "market_type"],
        date_columns=["trade_date"],
        required_columns=["ts_code", "trade_date", "market_type"],
        request_window_days=30,
    ),
    "cn_gdp": EndpointMeta(
        api_name="cn_gdp",
        description="国内生产总值 GDP",
        frequency="quarterly",
        group="macro_data",
        primary_keys=["quarter"],
    ),
    "cn_cpi": EndpointMeta(
        api_name="cn_cpi",
        description="居民消费价格指数 CPI",
        frequency="monthly",
        group="macro_data",
        primary_keys=["month"],
    ),
    "cn_ppi": EndpointMeta(
        api_name="cn_ppi",
        description="工业生产者出厂价格指数 PPI",
        frequency="monthly",
        group="macro_data",
        primary_keys=["month"],
    ),
    "cn_pmi": EndpointMeta(
        api_name="cn_pmi",
        description="采购经理人指数 PMI",
        frequency="monthly",
        group="macro_data",
        primary_keys=["month"],
    ),
    "cn_m": EndpointMeta(
        api_name="cn_m",
        description="货币供应量 M0/M1/M2",
        frequency="monthly",
        group="macro_data",
        primary_keys=["month"],
    ),
    "sf_month": EndpointMeta(
        api_name="sf_month",
        description="社会融资规模",
        frequency="monthly",
        group="macro_data",
        primary_keys=["month"],
    ),
    "shibor_lpr": EndpointMeta(
        api_name="shibor_lpr",
        description="LPR 贷款基础利率",
        frequency="monthly",
        group="macro_data",
        primary_keys=["date"],
    ),
    "fund_basic": EndpointMeta(
        api_name="fund_basic",
        description="基金基本信息",
        group="basic_info",
        primary_keys=["ts_code"],
    ),
    "fund_daily": EndpointMeta(
        api_name="fund_daily",
        description="基金日线行情",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
    ),
    "fund_adj": EndpointMeta(
        api_name="fund_adj",
        description="场内基金复权因子",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
    ),
    "fund_share": EndpointMeta(
        api_name="fund_share",
        description="基金份额规模",
        group="market_indicators",
        primary_keys=["ts_code", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["ts_code", "trade_date"],
    ),
    "etf_share_size": EndpointMeta(
        api_name="etf_share_size",
        description="ETF 基金份额与资产规模",
        group="market_indicators",
        primary_keys=["ts_code", "trade_date"],
    ),
}

# 公开项目任务名与 TuShare API 名称分离；采集器只通过 api_name 发起请求。
TUSHARE_TASK_REGISTRY: dict[str, EndpointMeta] = {
    "stock_daily_bar": TUSHARE_API_REGISTRY["daily"],
}

# 对已注册但尚未逐项声明的接口，至少从自然键生成结构化基础契约；
# 具体业务单位和数值范围仍由后续 quality_profile 持续补充。
for _meta in TUSHARE_API_REGISTRY.values():
    if not _meta.required_columns:
        _meta.required_columns.extend(_meta.primary_keys)
    if not _meta.date_columns:
        _meta.date_columns.extend(
            key for key in _meta.primary_keys if key in {"trade_date", "end_date", "suspend_date", "month", "quarter", "date"}
        )

# 基于 TuShare 本地接口目录的业务字段 profile。字段采用“最小稳定集合”，
# 允许源端新增字段，但禁止关键识别/日期/行情字段缺失。
_TUSHARE_PROFILES: dict[str, tuple[list[str], dict[str, str], str]] = {
    "daily": (["ts_code", "trade_date", "open", "high", "low", "close"],
              {"open": "CNY/share", "high": "CNY/share", "low": "CNY/share", "close": "CNY/share", "vol": "share", "amount": "CNY"}, "bar"),
    "index_daily": (["ts_code", "trade_date", "open", "high", "low", "close"],
                    {"open": "point", "high": "point", "low": "point", "close": "point", "vol": "share", "amount": "CNY"}, "bar"),
    "fund_daily": (["ts_code", "trade_date", "open", "high", "low", "close"],
                    {"open": "CNY/share", "high": "CNY/share", "low": "CNY/share", "close": "CNY/share", "vol": "share", "amount": "CNY"}, "bar"),
    "daily_basic": (["ts_code", "trade_date"], {"turnover_rate": "percent", "pe": "ratio", "pb": "ratio", "total_mv": "CNY10k"}, "market_indicator"),
    "index_dailybasic": (["ts_code", "trade_date"], {"pe": "ratio", "pb": "ratio", "turnover_rate": "percent"}, "market_indicator"),
    "adj_factor": (["ts_code", "trade_date", "adj_factor"], {"adj_factor": "factor"}, "corporate_action"),
    "income": (["ts_code", "end_date", "report_type"], {"revenue": "CNY", "n_income": "CNY"}, "financial_statement"),
    "fina_indicator": (["ts_code", "end_date"], {"roe": "percent", "grossprofit_margin": "percent", "netprofit_margin": "percent"}, "financial_indicator"),
    "suspend_d": (["ts_code", "trade_date"], {}, "event"),
    "index_weight": (["index_code", "con_code", "trade_date", "weight"], {"weight": "percent"}, "constituent_weight"),
    "margin": (["trade_date", "exchange_id"], {"rzye": "CNY10k", "rqye": "CNY10k"}, "margin_summary"),
    "margin_detail": (["ts_code", "trade_date"], {"rzye": "CNY10k", "rqye": "CNY10k"}, "margin_detail"),
    "moneyflow_hsgt": (["trade_date"], {"net_mf_amount": "CNY10k"}, "northbound_flow"),
    "hsgt_top10": (["trade_date", "ts_code", "market_type"], {"buy_amount": "CNY10k", "sell_amount": "CNY10k"}, "northbound_top10"),
    "fund_basic": (["ts_code", "name", "fund_type"], {}, "static"),
    "fund_share": (["ts_code", "trade_date", "fd_share"], {"fd_share": "share"}, "fund_share"),
    "etf_share_size": (["ts_code", "trade_date", "total_share"], {"total_share": "share"}, "fund_share"),
    "sw_daily": (["ts_code", "trade_date", "open", "high", "low", "close"], {"close": "point", "vol": "share", "amount": "CNY"}, "bar"),
    "cn_gdp": (["quarter"], {"gdp": "CNY100m", "gdp_yoy": "percent"}, "macro_quarterly"),
    "cn_cpi": (["month"], {"nt_val": "index", "nt_yoy": "percent"}, "macro_monthly"),
    "cn_ppi": (["month"], {"ppi": "index", "ppi_yoy": "percent"}, "macro_monthly"),
    "cn_pmi": (["month"], {"pmi": "index"}, "macro_monthly"),
    "cn_m": (["month"], {"m0": "CNY100m", "m1": "CNY100m", "m2": "CNY100m"}, "macro_monthly"),
    "sf_month": (["month"], {"social_financing": "CNY100m"}, "macro_monthly"),
    "shibor_lpr": (["date"], {"1y": "percent", "5y": "percent"}, "macro_rate"),
}
for _endpoint, (_required, _units, _profile) in _TUSHARE_PROFILES.items():
    if _endpoint in TUSHARE_API_REGISTRY:
        _meta = TUSHARE_API_REGISTRY[_endpoint]
        _meta.required_columns[:] = _required
        _meta.units.update(_units)
        object.__setattr__(_meta, "quality_profile", _profile)
