"""理杏仁 (Lixinger) 接口元数据注册表模块。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EndpointMeta:
    """理杏仁接口元数据描述。"""

    api_name: str
    description: str
    group: str = "market_data"
    primary_keys: list[str] = field(default_factory=list)
    rate_limit_per_min: int = 1000
    update_time: str = "18:00"
    update_delay_days: int = 0


# 常用理杏仁 API 接口元数据注册表
LIXINGER_API_REGISTRY: dict[str, EndpointMeta] = {
    "cn/company/fundamental/non_financial": EndpointMeta(
        api_name="cn/company/fundamental/non_financial",
        description="A 股非金融公司基本面估值数据",
        group="fundamental",
        primary_keys=["stockCode", "date"],
        rate_limit_per_min=1000,
        update_time="18:00",
        update_delay_days=0,
    ),
    "cn/company/candlestick": EndpointMeta(
        api_name="cn/company/candlestick",
        description="A 股公司 K 线行情数据",
        group="market_data",
        primary_keys=["stockCode", "date"],
        rate_limit_per_min=1000,
        update_time="17:00",
        update_delay_days=0,
    ),
    "cn/index/fundamental": EndpointMeta(
        api_name="cn/index/fundamental",
        description="A 股指数基本面估值数据",
        group="fundamental",
        primary_keys=["stockCode", "date"],
        rate_limit_per_min=1000,
        update_time="18:00",
        update_delay_days=0,
    ),
    "cn/index/candlestick": EndpointMeta(
        api_name="cn/index/candlestick",
        description="A 股指数 K 线行情数据",
        group="market_data",
        primary_keys=["stockCode", "date"],
        rate_limit_per_min=1000,
        update_time="17:00",
        update_delay_days=0,
    ),
    "cn/industry/fundamental/sw_2021": EndpointMeta(
        api_name="cn/industry/fundamental/sw_2021",
        description="申万 2021 版行业基本面估值数据",
        group="fundamental",
        primary_keys=["stockCode", "date"],
        rate_limit_per_min=1000,
        update_time="18:00",
        update_delay_days=0,
    ),
    "cn/industry/constituents/sw_2021": EndpointMeta(
        api_name="cn/industry/constituents/sw_2021",
        description="申万 2021 版行业成分股列表",
        group="basic_info",
        primary_keys=["stockCode", "date"],
        rate_limit_per_min=1000,
        update_time="18:00",
        update_delay_days=0,
    ),
}
