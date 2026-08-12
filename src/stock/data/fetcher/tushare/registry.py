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
}
