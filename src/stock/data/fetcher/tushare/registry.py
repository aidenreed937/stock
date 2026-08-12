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
}
