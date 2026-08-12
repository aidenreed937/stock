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
    "financials": YFinanceEndpointMeta(
        api_name="financials",
        description="利润表 (包含营收、净利润、毛利、EBITDA)",
        group="financial_reports",
        primary_keys=["symbol", "asOfDate"],
        rate_limit_per_min=60,
    ),
    "balance_sheet": YFinanceEndpointMeta(
        api_name="balance_sheet",
        description="资产负债表 (包含总资产、总负债、股东权益、现金)",
        group="financial_reports",
        primary_keys=["symbol", "asOfDate"],
        rate_limit_per_min=60,
    ),
    "cashflow": YFinanceEndpointMeta(
        api_name="cashflow",
        description="现金流量表 (包含经营现金流、资本支出、自由现金流 FCF)",
        group="financial_reports",
        primary_keys=["symbol", "asOfDate"],
        rate_limit_per_min=60,
    ),
    "dividends": YFinanceEndpointMeta(
        api_name="dividends",
        description="历史派息记录",
        group="corporate_actions",
        primary_keys=["symbol", "Date"],
        rate_limit_per_min=60,
    ),
    "splits": YFinanceEndpointMeta(
        api_name="splits",
        description="历史拆股记录",
        group="corporate_actions",
        primary_keys=["symbol", "Date"],
        rate_limit_per_min=60,
    ),
    "analyst_price_target": YFinanceEndpointMeta(
        api_name="analyst_price_target",
        description="分析师目标价 (最高、最低、均值、中位数)",
        group="market_indicators",
        primary_keys=["symbol", "trade_date"],
        rate_limit_per_min=60,
    ),
    "recommendations": YFinanceEndpointMeta(
        api_name="recommendations",
        description="机构评级分布与评级变更记录",
        group="market_indicators",
        primary_keys=["symbol", "period"],
        rate_limit_per_min=60,
    ),
    "institutional_holders": YFinanceEndpointMeta(
        api_name="institutional_holders",
        description="机构投资者与大股东持仓数据",
        group="holders_info",
        primary_keys=["symbol", "Holder"],
        rate_limit_per_min=60,
    ),
    "insider_transactions": YFinanceEndpointMeta(
        api_name="insider_transactions",
        description="高管与内部人买卖交易记录",
        group="holders_info",
        primary_keys=["symbol", "Start Date", "Insider"],
        rate_limit_per_min=60,
    ),
    "fast_info": YFinanceEndpointMeta(
        api_name="fast_info",
        description="盘前盘后极速行情快照 (最新价、盘前/盘后价、52周高低)",
        group="market_data",
        primary_keys=["symbol", "trade_date"],
        rate_limit_per_min=120,
    ),
}
