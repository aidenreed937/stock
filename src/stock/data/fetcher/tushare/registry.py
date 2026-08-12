"""TuShare 接口元数据注册表模块。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EndpointMeta:
    """TuShare 接口元数据描述。"""

    api_name: str
    description: str
    group: str = "market_data"
    primary_keys: list[str] = field(default_factory=list)
    rate_limit_per_min: int = 200


# 常用 TuShare 接口元数据注册表
TUSHARE_API_REGISTRY: dict[str, EndpointMeta] = {
    "daily": EndpointMeta(
        api_name="daily",
        description="A 股日线行情",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        rate_limit_per_min=500,
    ),
    "daily_basic": EndpointMeta(
        api_name="daily_basic",
        description="每日指标（换手率、PE、PB、总市值等）",
        group="market_indicators",
        primary_keys=["ts_code", "trade_date"],
        rate_limit_per_min=500,
    ),
    "stock_basic": EndpointMeta(
        api_name="stock_basic",
        description="基础股票列表",
        group="basic_info",
        primary_keys=["ts_code"],
        rate_limit_per_min=100,
    ),
    "adj_factor": EndpointMeta(
        api_name="adj_factor",
        description="复权因子数据",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        rate_limit_per_min=500,
    ),
    "income": EndpointMeta(
        api_name="income",
        description="上市公司利润表",
        group="financial_statements",
        primary_keys=["ts_code", "end_date"],
        rate_limit_per_min=100,
    ),
    "index_daily": EndpointMeta(
        api_name="index_daily",
        description="指数日线行情",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        rate_limit_per_min=500,
    ),
    "suspend_d": EndpointMeta(
        api_name="suspend_d",
        description="每日停复牌信息",
        group="market_data",
        primary_keys=["ts_code", "suspend_date"],
        rate_limit_per_min=100,
    ),
    "fina_indicator": EndpointMeta(
        api_name="fina_indicator",
        description="财务指标数据（ROE/毛利率等）",
        group="financial_statements",
        primary_keys=["ts_code", "end_date"],
        rate_limit_per_min=100,
    ),
    "moneyflow": EndpointMeta(
        api_name="moneyflow",
        description="个股资金流向",
        group="money_flow",
        primary_keys=["ts_code", "trade_date"],
        rate_limit_per_min=500,
    ),
    "hk_hold": EndpointMeta(
        api_name="hk_hold",
        description="沪深港通持股明细（北向资金）",
        group="money_flow",
        primary_keys=["ts_code", "trade_date"],
        rate_limit_per_min=100,
    ),
    "index_basic": EndpointMeta(
        api_name="index_basic",
        description="指数基本信息",
        group="basic_info",
        primary_keys=["ts_code"],
        rate_limit_per_min=100,
    ),
    "index_dailybasic": EndpointMeta(
        api_name="index_dailybasic",
        description="指数每日估值与指标",
        group="market_indicators",
        primary_keys=["ts_code", "trade_date"],
        rate_limit_per_min=100,
    ),
    "index_weight": EndpointMeta(
        api_name="index_weight",
        description="指数成分股权重",
        group="basic_info",
        primary_keys=["index_code", "con_code", "trade_date"],
        rate_limit_per_min=100,
    ),
    "index_classify": EndpointMeta(
        api_name="index_classify",
        description="申万行业分类",
        group="basic_info",
        primary_keys=["index_code"],
        rate_limit_per_min=100,
    ),
    "index_member": EndpointMeta(
        api_name="index_member",
        description="申万行业成分股",
        group="basic_info",
        primary_keys=["index_code", "con_code"],
        rate_limit_per_min=100,
    ),
    "sw_daily": EndpointMeta(
        api_name="sw_daily",
        description="申万行业日线行情",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        rate_limit_per_min=100,
    ),
    "margin": EndpointMeta(
        api_name="margin",
        description="融资融券交易汇总",
        group="market_indicators",
        primary_keys=["trade_date", "exchange_id"],
        rate_limit_per_min=100,
    ),
    "margin_detail": EndpointMeta(
        api_name="margin_detail",
        description="融资融券交易明细",
        group="market_data",
        primary_keys=["ts_code", "trade_date"],
        rate_limit_per_min=100,
    ),
    "moneyflow_hsgt": EndpointMeta(
        api_name="moneyflow_hsgt",
        description="沪深港通资金流向",
        group="money_flow",
        primary_keys=["trade_date"],
        rate_limit_per_min=100,
    ),
    "hsgt_top10": EndpointMeta(
        api_name="hsgt_top10",
        description="沪深港通十大成交股",
        group="money_flow",
        primary_keys=["trade_date", "ts_code", "market_type"],
        rate_limit_per_min=100,
    ),
    "cn_gdp": EndpointMeta(
        api_name="cn_gdp",
        description="国内生产总值 GDP",
        group="macro_data",
        primary_keys=["quarter"],
        rate_limit_per_min=100,
    ),
    "cn_cpi": EndpointMeta(
        api_name="cn_cpi",
        description="居民消费价格指数 CPI",
        group="macro_data",
        primary_keys=["month"],
        rate_limit_per_min=100,
    ),
    "cn_ppi": EndpointMeta(
        api_name="cn_ppi",
        description="工业生产者出厂价格指数 PPI",
        group="macro_data",
        primary_keys=["month"],
        rate_limit_per_min=100,
    ),
    "cn_pmi": EndpointMeta(
        api_name="cn_pmi",
        description="采购经理人指数 PMI",
        group="macro_data",
        primary_keys=["month"],
        rate_limit_per_min=100,
    ),
    "cn_m": EndpointMeta(
        api_name="cn_m",
        description="货币供应量 M0/M1/M2",
        group="macro_data",
        primary_keys=["month"],
        rate_limit_per_min=100,
    ),
    "sf_month": EndpointMeta(
        api_name="sf_month",
        description="社会融资规模",
        group="macro_data",
        primary_keys=["month"],
        rate_limit_per_min=100,
    ),
    "shibor_lpr": EndpointMeta(
        api_name="shibor_lpr",
        description="LPR 贷款基础利率",
        group="macro_data",
        primary_keys=["date"],
        rate_limit_per_min=100,
    ),
}
