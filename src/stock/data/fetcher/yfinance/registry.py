from dataclasses import dataclass, field


@dataclass(frozen=True)
class YFinanceEndpointMeta:
    """Yahoo Finance 接口元数据描述。"""

    api_name: str
    description: str
    group: str = "market_data"
    primary_keys: list[str] = field(default_factory=list)


# YFinance 接口元数据注册表
YFINANCE_API_REGISTRY: dict[str, YFinanceEndpointMeta] = {
    "history": YFinanceEndpointMeta(
        api_name="history",
        description="日线 K 线行情",
        group="market_data",
        primary_keys=["Date"],
    ),
}
