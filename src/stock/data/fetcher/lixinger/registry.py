from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EndpointMeta:
    """理杏仁接口元数据描述。"""

    api_name: str
    description: str
    market: str = "CN"
    group: str = "market_data"
    primary_keys: list[str] = field(default_factory=list)
    rate_limit_per_min: int = 30
    update_time: str = "18:00"
    update_delay_days: int = 0
    default_metrics: list[str] = field(default_factory=list)
    default_params: dict[str, Any] = field(default_factory=dict)
    code_param_name: str = "stockCodes"
    support_batch_prefetch: bool = False



# 常用理杏仁 API 接口元数据注册表 (全局统一由 LixingerClient / data.yaml 控制限频)
LIXINGER_API_REGISTRY: dict[str, EndpointMeta] = {
    "cn/company/fundamental/non_financial": EndpointMeta(
        api_name="cn/company/fundamental/non_financial",
        description="A 股非金融公司基本面估值数据",
        group="fundamental",
        primary_keys=["stockCode", "date"],
        update_time="18:00",
        update_delay_days=0,
        code_param_name="stockCodes",
        default_metrics=["pe_ttm", "pb", "ps_ttm", "dyr", "mc"],
        support_batch_prefetch=True,
    ),
    "cn/company/candlestick": EndpointMeta(
        api_name="cn/company/candlestick",
        description="A 股公司 K 线行情数据",
        group="market_data",
        primary_keys=["stockCode", "date"],
        update_time="17:00",
        update_delay_days=0,
        code_param_name="stockCode",
        default_params={"type": "ex_rights"},
    ),
    "cn/index/fundamental": EndpointMeta(
        api_name="cn/index/fundamental",
        description="A 股指数基本面估值数据",
        group="fundamental",
        primary_keys=["stockCode", "date"],
        update_time="18:00",
        update_delay_days=0,
        code_param_name="stockCodes",
        default_metrics=["pe_ttm.ew", "pb.ew", "ps_ttm.ew", "dyr.ew", "mc"],
    ),
    "cn/index/candlestick": EndpointMeta(
        api_name="cn/index/candlestick",
        description="A 股指数 K 线行情数据",
        group="market_data",
        primary_keys=["stockCode", "date"],
        update_time="17:00",
        update_delay_days=0,
        code_param_name="stockCode",
        default_params={"type": "normal"},
    ),
    "cn/industry/fundamental/sw_2021": EndpointMeta(
        api_name="cn/industry/fundamental/sw_2021",
        description="申万 2021 版行业基本面估值数据",
        group="fundamental",
        primary_keys=["stockCode", "date"],
        update_time="18:00",
        update_delay_days=0,
        code_param_name="stockCodes",
        default_metrics=["pe_ttm.ew", "pb.ew", "ps_ttm.ew", "dyr.ew", "mc"],
    ),
    "cn/industry/constituents/sw_2021": EndpointMeta(
        api_name="cn/industry/constituents/sw_2021",
        description="申万 2021 版行业成分股列表",
        group="basic_info",
        primary_keys=["stockCode", "date"],
        update_time="18:00",
        update_delay_days=0,
        code_param_name="stockCodes",
    ),
    "cn/company/fs/non_financial": EndpointMeta(
        api_name="cn/company/fs/non_financial",
        description="A 股非金融公司财务报表 (含商誉、经营现金流、净资产与审计意见)",
        group="financial_statement",
        primary_keys=["stockCode", "date"],
        update_time="18:00",
        update_delay_days=0,
        code_param_name="stockCodes",
        default_metrics=["goodwill", "operating_cash_flow", "equity", "audit_opinion", "interest_bearing_debt"],
        support_batch_prefetch=True,
    ),
    "cn/company/hot/ple": EndpointMeta(
        api_name="cn/company/hot/ple",
        description="A 股公司股权质押汇总 (含大股东质押率与全公司质押率)",
        group="risk_control",
        primary_keys=["stockCode", "date"],
        update_time="18:00",
        update_delay_days=0,
        code_param_name="stockCodes",
        default_metrics=["pledge_ratio", "major_shareholder_pledge_ratio"],
        support_batch_prefetch=True,
    ),
}

# 增加 CLI 常用短别名映射
LIXINGER_API_REGISTRY["sw_2021_constituents"] = LIXINGER_API_REGISTRY["cn/industry/constituents/sw_2021"]
LIXINGER_API_REGISTRY["sw_2021_fundamental"] = LIXINGER_API_REGISTRY["cn/industry/fundamental/sw_2021"]
LIXINGER_API_REGISTRY["index_fundamental"] = LIXINGER_API_REGISTRY["cn/index/fundamental"]
LIXINGER_API_REGISTRY["fs_non_financial"] = LIXINGER_API_REGISTRY["cn/company/fs/non_financial"]
LIXINGER_API_REGISTRY["pledge_info"] = LIXINGER_API_REGISTRY["cn/company/hot/ple"]
