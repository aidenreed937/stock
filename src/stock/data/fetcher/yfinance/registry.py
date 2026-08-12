from dataclasses import dataclass, field


@dataclass(frozen=True)
class YFinanceEndpointMeta:
    """Yahoo Finance 接口元数据描述。"""

    api_name: str
    description: str
    group: str = "market_data"
    primary_keys: list[str] = field(default_factory=list)
    rate_limit_per_min: int = 60
    update_time: str = "06:00"
    update_delay_days: int = 1


# YFinance 接口元数据注册表
YFINANCE_API_REGISTRY: dict[str, YFinanceEndpointMeta] = {
    "history": YFinanceEndpointMeta(
        api_name="history",
        description="日线 K 线行情 (包含个股 stock_daily_bar 与指数 index_daily_bar)",
        group="market_data",
        primary_keys=["Date"],
        rate_limit_per_min=60,
        update_time="06:00",
        update_delay_days=1,
    ),
    "index_valuation": YFinanceEndpointMeta(
        api_name="index_valuation",
        description="核心 ETF 指数级实时估值指标 (PE-TTM / Forward PE / PB / 股息率)",
        group="market_indicators",
        primary_keys=["symbol", "trade_date"],
        rate_limit_per_min=60,
        update_time="06:00",
        update_delay_days=0,
    ),
}
