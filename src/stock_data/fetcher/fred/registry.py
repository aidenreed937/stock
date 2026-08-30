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


# FRED 常用核心官方宏观指标注册表
FRED_API_REGISTRY: dict[str, FREDEndpointMeta] = {
    "FEDFUNDS": FREDEndpointMeta(
        series_id="FEDFUNDS",
        description="美联储联邦基金有效利率 (Effective Federal Funds Rate)",
        frequency="monthly",
        units="percent",
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
    "NAPM": FREDEndpointMeta(
        series_id="NAPM",
        description="美国 ISM 制造业采购经理人指数 (ISM Manufacturing PMI)",
        frequency="monthly",
        units="index",
    ),
    "MANEMP": FREDEndpointMeta(
        series_id="MANEMP",
        description="美国 ISM 制造业就业指数 (ISM Manufacturing: Employment Index)",
        frequency="monthly",
        units="index",
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
}
