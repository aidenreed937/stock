from dataclasses import dataclass, field


@dataclass(frozen=True)
class AlphaVantageEndpointMeta:
    """Alpha Vantage endpoint metadata."""

    api_name: str
    description: str
    market: str = "GLOBAL"
    frequency: str = "daily"
    group: str = "macro_data"
    quality_profile: str = "macro"
    primary_keys: list[str] = field(default_factory=lambda: ["symbol", "trade_date"])
    date_columns: list[str] = field(default_factory=lambda: ["trade_date"])
    required_columns: list[str] = field(
        default_factory=lambda: [
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
        ]
    )
    rate_limit_per_min: int = 5
    update_time: str = "06:00"
    update_delay_days: int = 0
    max_range_days: int | None = None
    fetch_mode: str = "per_symbol"
    partitioned: bool = True
    is_single_sync: bool | None = None
    dataset: str | None = None
    query_mode: str = "trade_date"


ALPHAVANTAGE_API_REGISTRY: dict[str, AlphaVantageEndpointMeta] = {
    "TIME_SERIES_DAILY": AlphaVantageEndpointMeta(
        api_name="TIME_SERIES_DAILY",
        description="Global equity raw daily OHLCV data",
        market="US",
        group="market_data",
        quality_profile="bar",
        primary_keys=["symbol", "trade_date"],
        required_columns=[
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ],
        update_time="06:00",
        update_delay_days=1,
    ),
    "FX_DAILY": AlphaVantageEndpointMeta(
        api_name="FX_DAILY",
        description="Daily foreign exchange OHLC data for USD/CNH and other supported pairs",
        update_delay_days=1,
    ),
    "OVERVIEW": AlphaVantageEndpointMeta(
        api_name="OVERVIEW",
        description="Company overview and current valuation snapshot",
        market="US",
        frequency="static",
        group="basic_info",
        quality_profile="generic",
        primary_keys=["symbol"],
        date_columns=["as_of_date", "latest_quarter"],
        required_columns=["symbol"],
        partitioned=False,
        is_single_sync=True,
    ),
    "EARNINGS": AlphaVantageEndpointMeta(
        api_name="EARNINGS",
        description="Annual and quarterly company earnings history",
        market="US",
        frequency="quarterly",
        group="financial_reports",
        quality_profile="generic",
        query_mode="period",
        primary_keys=["symbol", "report_type", "fiscal_date_ending"],
        date_columns=["fiscal_date_ending", "reported_date"],
        required_columns=["symbol", "report_type", "fiscal_date_ending"],
        partitioned=False,
        is_single_sync=True,
    ),
    "INCOME_STATEMENT": AlphaVantageEndpointMeta(
        api_name="INCOME_STATEMENT",
        description="Annual and quarterly income statement",
        market="US",
        frequency="quarterly",
        group="financial_reports",
        quality_profile="generic",
        query_mode="period",
        primary_keys=["symbol", "report_type", "fiscal_date_ending"],
        date_columns=["fiscal_date_ending", "reported_date"],
        required_columns=["symbol", "report_type", "fiscal_date_ending"],
        partitioned=False,
        is_single_sync=True,
    ),
    "BALANCE_SHEET": AlphaVantageEndpointMeta(
        api_name="BALANCE_SHEET",
        description="Annual and quarterly balance sheet",
        market="US",
        frequency="quarterly",
        group="financial_reports",
        quality_profile="generic",
        query_mode="period",
        primary_keys=["symbol", "report_type", "fiscal_date_ending"],
        date_columns=["fiscal_date_ending", "reported_date"],
        required_columns=["symbol", "report_type", "fiscal_date_ending"],
        partitioned=False,
        is_single_sync=True,
    ),
    "CASH_FLOW": AlphaVantageEndpointMeta(
        api_name="CASH_FLOW",
        description="Annual and quarterly cash flow statement",
        market="US",
        frequency="quarterly",
        group="financial_reports",
        quality_profile="generic",
        query_mode="period",
        primary_keys=["symbol", "report_type", "fiscal_date_ending"],
        date_columns=["fiscal_date_ending", "reported_date"],
        required_columns=["symbol", "report_type", "fiscal_date_ending"],
        partitioned=False,
        is_single_sync=True,
    ),
}
