from dataclasses import dataclass, field


@dataclass(frozen=True)
class FREDEndpointMeta:
    """FRED (Federal Reserve Economic Data) 宏观接口元数据。"""

    series_id: str
    description: str
    market: str = "US"
    frequency: str = "monthly"  # monthly, daily, quarterly
    group: str = "macro_data"
    primary_keys: list[str] = field(default_factory=lambda: ["symbol", "trade_date"])
    date_columns: list[str] = field(default_factory=lambda: ["trade_date"])
    required_columns: list[str] = field(default_factory=lambda: ["symbol", "trade_date"])
    rate_limit_per_min: int = 120
    units: str = "index"
    max_range_days: int | None = None
    query_mode: str = "trade_date"
    fetch_mode: str = "per_symbol"
    partitioned: bool = False
    is_single_sync: bool = True
    dataset: str = "macro_indicators"
    quality_profile: str = "generic"
    update_time: str = "18:00"
    update_delay_days: int = 0


# FRED 常用核心官方宏观指标注册表
FRED_API_REGISTRY: dict[str, FREDEndpointMeta] = {
    "macro_indicators": FREDEndpointMeta(
        series_id="macro_indicators",
        description="FRED 核心宏观指标聚合任务",
        frequency="monthly",
        group="macro_data",
        quality_profile="macro",
    ),
    "FEDFUNDS": FREDEndpointMeta(
        series_id="FEDFUNDS",
        description="美联储联邦基金有效利率 (Effective Federal Funds Rate)",
        frequency="monthly",
        units="percent",
    ),
    "DFF": FREDEndpointMeta(
        series_id="DFF",
        description="美联储联邦基金有效利率（日频，Effective Federal Funds Rate）",
        frequency="daily",
        units="percent",
        update_time="18:00",
        update_delay_days=1,
    ),
    "CPIAUCSL": FREDEndpointMeta(
        series_id="CPIAUCSL",
        description="美国 CPI 消费者物价指数 (Consumer Price Index)",
        frequency="monthly",
        units="index",
    ),
    "UNRATE": FREDEndpointMeta(
        series_id="UNRATE",
        description="美国失业率 (Unemployment Rate)",
        frequency="monthly",
        units="percent",
    ),
    "PAYEMS": FREDEndpointMeta(
        series_id="PAYEMS",
        description="美国非农就业总人数 (Total Nonfarm Payrolls)",
        frequency="monthly",
        units="thousands",
    ),
    "GDP": FREDEndpointMeta(
        series_id="GDP",
        description="美国国内生产总值 GDP (Gross Domestic Product)",
        frequency="quarterly",
        units="billions_usd",
    ),
    "T10Y2Y": FREDEndpointMeta(
        series_id="T10Y2Y",
        description="美国 10 年期与 2 年期国债收益率利差 (10Y-2Y Spread)",
        frequency="daily",
        units="percent",
    ),
    "WALCL": FREDEndpointMeta(
        series_id="WALCL",
        description="美联储总资产规模 (Assets: Total Assets)",
        frequency="weekly",
        units="millions_usd",
    ),
    "MANEMP": FREDEndpointMeta(
        series_id="MANEMP",
        description="美国制造业就业人数 (BLS: All Employees, Manufacturing)",
        frequency="monthly",
        units="thousands",
    ),
    "OECDLOLITOAASTSAM": FREDEndpointMeta(
        series_id="OECDLOLITOAASTSAM",
        description="OECD 全球综合领先指标 (OECD Composite Leading Indicator)",
        frequency="monthly",
        units="index",
    ),
    "USALOLITOAASTSAM": FREDEndpointMeta(
        series_id="USALOLITOAASTSAM",
        description="美国 OECD 综合领先指标 (OECD CLI for USA)",
        frequency="monthly",
        units="index",
    ),
    "CHNLOLITOAASTSAM": FREDEndpointMeta(
        series_id="CHNLOLITOAASTSAM",
        description="中国 OECD 综合领先指标 (OECD CLI for China)",
        frequency="monthly",
        units="index",
    ),
    "DGORDER": FREDEndpointMeta(
        series_id="DGORDER",
        description="美国耐用品新增订单 (Manufacturers' New Orders: Durable Goods)",
        frequency="monthly",
        units="millions_usd",
    ),
    "AMTMVS": FREDEndpointMeta(
        series_id="AMTMVS",
        description="美国制造业出货额 (Manufacturers' Shipments: Total Manufacturing)",
        frequency="monthly",
        units="millions_usd",
    ),
    "DEXTAUS": FREDEndpointMeta(
        series_id="DEXTAUS",
        description="美元兑新台币即期汇率 (Taiwan Dollars to U.S. Dollar Spot Exchange Rate, H.10 日频)",
        frequency="daily",
        units="twd_per_usd",
        max_range_days=3650,
    ),
    "DEXCHUS": FREDEndpointMeta(
        series_id="DEXCHUS",
        description="美元兑在岸人民币即期汇率 (China / U.S. Foreign Exchange Rate, H.10 日频)",
        frequency="daily",
        units="cny_per_usd",
        max_range_days=3650,
    ),
    "DEXJPUS": FREDEndpointMeta(
        series_id="DEXJPUS",
        description="美元兑日元即期汇率 (Japan / U.S. Foreign Exchange Rate, H.10 日频)",
        frequency="daily",
        units="jpy_per_usd",
        max_range_days=3650,
    ),
    "DEXUSEU": FREDEndpointMeta(
        series_id="DEXUSEU",
        description="欧元兑美元即期汇率 (U.S. / Euro Foreign Exchange Rate, H.10 日频)",
        frequency="daily",
        units="usd_per_eur",
        max_range_days=3650,
    ),
    "DEXKOUS": FREDEndpointMeta(
        series_id="DEXKOUS",
        description="美元兑韩元即期汇率 (South Korean Won to U.S. Dollar Spot Exchange Rate, H.10 日频)",
        frequency="daily",
        units="krw_per_usd",
        max_range_days=3650,
    ),
    "DGS10": FREDEndpointMeta(
        series_id="DGS10",
        description="美国 10 年期国债常数到期收益率 (Treasury Constant Maturity Rate)",
        frequency="daily",
        units="percent",
    ),
    "DGS3MO": FREDEndpointMeta(
        series_id="DGS3MO",
        description="美国 3 个月国债恒定期限市场收益率 (3-Month Treasury Constant Maturity)",
        frequency="daily",
        units="percent",
    ),
    "VIXCLS": FREDEndpointMeta(
        series_id="VIXCLS",
        description="CBOE VIX 恐慌指数收盘值",
        frequency="daily",
        units="index",
        update_time="23:00",
        update_delay_days=1,
    ),
    "DCOILWTICO": FREDEndpointMeta(
        series_id="DCOILWTICO",
        description="WTI 西德州中质原油现货价格",
        frequency="daily",
        units="dollars_per_barrel",
    ),
    "DTWEXBGS": FREDEndpointMeta(
        series_id="DTWEXBGS",
        description="名义广义美元指数",
        frequency="daily",
        units="index_jan_2006_100",
    ),
    "PCOPPUSDM": FREDEndpointMeta(
        series_id="PCOPPUSDM",
        description="全球铜价格（月频，美元/公吨）",
        frequency="monthly",
        units="dollars_per_metric_ton",
    ),
}
