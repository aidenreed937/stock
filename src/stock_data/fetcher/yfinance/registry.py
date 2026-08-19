from dataclasses import dataclass, field


@dataclass(frozen=True)
class YFinanceEndpointMeta:
    """Yahoo Finance 接口元数据描述。"""

    api_name: str
    description: str
    market: str = "US"
    frequency: str = "daily"  # daily, monthly, quarterly, event
    group: str = "market_data"
    primary_keys: list[str] = field(default_factory=list)
    rate_limit_per_min: int = 40
    update_time: str = "06:00"
    update_delay_days: int = 1
    date_columns: list[str] = field(default_factory=list)
    required_columns: list[str] = field(default_factory=list)
    max_range_days: int | None = None


# YFinance 接口元数据注册表 (全局统一由 YFinanceClient / data.yaml 控制限频)
YFINANCE_API_REGISTRY: dict[str, YFinanceEndpointMeta] = {
    "history": YFinanceEndpointMeta(
        api_name="history",
        description="日线 K 线行情 (包含个股 stock_daily_bar 与指数 index_daily_bar)",
        frequency="daily",
        group="market_data",
        primary_keys=["symbol", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["symbol", "trade_date"],
        update_time="06:00",
        update_delay_days=1,
    ),
    "index_valuation": YFinanceEndpointMeta(
        api_name="index_valuation",
        description="核心 ETF 指数级实时估值指标 (PE-TTM / Forward PE / PB / 股息率)",
        frequency="daily",
        group="market_indicators",
        primary_keys=["symbol", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["symbol", "trade_date"],
        update_time="06:00",
        update_delay_days=0,
    ),
    "macro_indicators": YFinanceEndpointMeta(
        api_name="macro_indicators",
        description="全球宏观资产日线行情（含 GC=F 黄金、CL=F 原油和 HG=F 铜期货）",
        market="GLOBAL",
        frequency="daily",
        group="macro_data",
        primary_keys=["symbol", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["symbol", "trade_date"],
        update_time="06:00",
        update_delay_days=1,
    ),
    "financials": YFinanceEndpointMeta(
        api_name="financials",
        description="利润表 (包含营收、净利润、毛利、EBITDA)",
        frequency="quarterly",
        group="financial_reports",
        primary_keys=["symbol", "as_of_date"],
        date_columns=["as_of_date"],
        required_columns=["symbol", "as_of_date"],
    ),
    "balance_sheet": YFinanceEndpointMeta(
        api_name="balance_sheet",
        description="资产负债表 (包含总资产、总负债、股东权益、现金)",
        frequency="quarterly",
        group="financial_reports",
        primary_keys=["symbol", "as_of_date"],
        date_columns=["as_of_date"],
        required_columns=["symbol", "as_of_date"],
    ),
    "cashflow": YFinanceEndpointMeta(
        api_name="cashflow",
        description="现金流量表 (包含经营现金流、资本支出、自由现金流 FCF)",
        frequency="quarterly",
        group="financial_reports",
        primary_keys=["symbol", "as_of_date"],
        date_columns=["as_of_date"],
        required_columns=["symbol", "as_of_date"],
    ),
    "dividends": YFinanceEndpointMeta(
        api_name="dividends",
        description="历史派息记录",
        frequency="event",
        group="corporate_actions",
        primary_keys=["symbol", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["symbol", "trade_date"],
    ),
    "splits": YFinanceEndpointMeta(
        api_name="splits",
        description="历史拆股记录",
        frequency="event",
        group="corporate_actions",
        primary_keys=["symbol", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["symbol", "trade_date"],
    ),
    "analyst_price_target": YFinanceEndpointMeta(
        api_name="analyst_price_target",
        description="分析师目标价 (最高、最低、均值、中位数)",
        frequency="daily",
        group="market_indicators",
        primary_keys=["symbol", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["symbol", "trade_date"],
    ),
    "recommendations": YFinanceEndpointMeta(
        api_name="recommendations",
        description="机构评级分布与评级变更记录",
        frequency="event",
        group="market_indicators",
        primary_keys=["symbol", "period"],
        required_columns=["symbol", "period"],
    ),
    "institutional_holders": YFinanceEndpointMeta(
        api_name="institutional_holders",
        description="机构投资者与大股东持仓数据",
        frequency="quarterly",
        group="holders_info",
        primary_keys=["symbol", "Holder"],
        required_columns=["symbol", "Holder"],
    ),
    "insider_transactions": YFinanceEndpointMeta(
        api_name="insider_transactions",
        description="高管与内部人买卖交易记录",
        frequency="event",
        group="holders_info",
        primary_keys=["symbol", "Start Date", "Insider"],
        date_columns=["Start Date"],
        required_columns=["symbol", "Start Date", "Insider"],
    ),
    "fast_info": YFinanceEndpointMeta(
        api_name="fast_info",
        description="盘前盘后极速行情快照 (最新价、盘前/盘后价、52周高低)",
        frequency="daily",
        group="market_data",
        primary_keys=["symbol", "trade_date"],
        date_columns=["trade_date"],
        required_columns=["symbol", "trade_date"],
    ),
}
