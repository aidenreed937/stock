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
    date_columns: list[str] = field(default_factory=list)
    required_columns: list[str] = field(default_factory=list)
    max_range_days: int | None = 3650
    pagination_required: bool = False



# 常用理杏仁 API 接口元数据注册表 (全局统一由 LixingerClient / data.yaml 控制限频)
LIXINGER_API_REGISTRY: dict[str, EndpointMeta] = {
    "cn/company/fundamental/non_financial": EndpointMeta(
        api_name="cn/company/fundamental/non_financial",
        description="A 股非金融公司基本面估值数据",
        group="fundamental",
        primary_keys=["stockCode", "date"],
        date_columns=["date"], required_columns=["stockCode", "date"],
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
        date_columns=["date"], required_columns=["stockCode", "date"],
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
        date_columns=["date"], required_columns=["stockCode", "date"],
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
        date_columns=["date"], required_columns=["stockCode", "date"],
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
        date_columns=["date"], required_columns=["stockCode", "date"],
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
        date_columns=["date"], required_columns=["stockCode", "date"],
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
    "macro/national-debt": EndpointMeta(
        api_name="macro/national-debt",
        description="国债收益率数据 (含中美国债 3M 至 30Y 期限结构)",
        group="macro_data",
        primary_keys=["areaCode", "date"],
        date_columns=["date"],
        required_columns=["areaCode", "date"],
        update_time="18:00",
        default_metrics=["tcm_y10", "tcm_y1", "tcm_y2", "tcm_y5", "tcm_y30"],
        default_params={"areaCode": "cn"},
    ),
    "macro/interest-rates": EndpointMeta(
        api_name="macro/interest-rates",
        description="宏观利率数据 (含 Shibor/同业存单/MLF/LPR/回购定盘利率)",
        group="macro_data",
        primary_keys=["areaCode", "date"],
        date_columns=["date"],
        required_columns=["areaCode", "date"],
        update_time="18:00",
        default_metrics=["shibor_on", "shibor_w1", "shibor_y1", "cdnaaa_y1", "lpr_y1", "lpr_y5", "fdr_d7"],
        default_params={"areaCode": "cn"},
    ),
    "macro/non-ferrous-metals": EndpointMeta(
        api_name="macro/non-ferrous-metals",
        description="全球有色金属现货价格数据 (伦敦铜/铝/锌/铅/镍/锡)",
        group="macro_data",
        primary_keys=["date"],
        date_columns=["date"],
        required_columns=["date"],
        update_time="18:00",
    ),
    "macro/crude-oil": EndpointMeta(
        api_name="macro/crude-oil",
        description="国际原油现货价格数据 (WTI 与布伦特原油)",
        group="macro_data",
        primary_keys=["date"],
        date_columns=["date"],
        required_columns=["date"],
        update_time="18:00",
    ),
}

# 增加 CLI 常用短别名映射
LIXINGER_API_REGISTRY["sw_2021_constituents"] = LIXINGER_API_REGISTRY["cn/industry/constituents/sw_2021"]
LIXINGER_API_REGISTRY["sw_2021_fundamental"] = LIXINGER_API_REGISTRY["cn/industry/fundamental/sw_2021"]
LIXINGER_API_REGISTRY["index_fundamental"] = LIXINGER_API_REGISTRY["cn/index/fundamental"]
LIXINGER_API_REGISTRY["fs_non_financial"] = LIXINGER_API_REGISTRY["cn/company/fs/non_financial"]
LIXINGER_API_REGISTRY["pledge_info"] = LIXINGER_API_REGISTRY["cn/company/hot/ple"]
LIXINGER_API_REGISTRY["national_debt"] = LIXINGER_API_REGISTRY["macro/national-debt"]
LIXINGER_API_REGISTRY["interest_rates"] = LIXINGER_API_REGISTRY["macro/interest-rates"]
LIXINGER_API_REGISTRY["non_ferrous_metals"] = LIXINGER_API_REGISTRY["macro/non-ferrous-metals"]
LIXINGER_API_REGISTRY["crude_oil"] = LIXINGER_API_REGISTRY["macro/crude-oil"]

for _meta in {id(meta): meta for meta in LIXINGER_API_REGISTRY.values()}.values():
    if not _meta.required_columns:
        _meta.required_columns.extend(_meta.primary_keys)
    if not _meta.date_columns:
        _meta.date_columns.extend(key for key in _meta.primary_keys if key in {"date", "endDate"})
