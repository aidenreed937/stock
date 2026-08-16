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


ALPHAVANTAGE_API_REGISTRY: dict[str, AlphaVantageEndpointMeta] = {
    "FX_DAILY": AlphaVantageEndpointMeta(
        api_name="FX_DAILY",
        description="Daily foreign exchange OHLC data for USD/CNH and other supported pairs",
    ),
}
