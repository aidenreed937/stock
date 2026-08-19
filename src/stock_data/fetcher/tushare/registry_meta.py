"""TuShare 接口元数据 dataclass 定义。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EndpointMeta:
    """TuShare 接口元数据描述。"""

    api_name: str
    description: str
    market: str = "CN"
    frequency: str = "daily"  # daily, monthly, quarterly, event
    query_mode: str = "trade_date"  # trade_date, ann_date, date, month, quarter
    group: str = "market_data"
    primary_keys: list[str] = field(default_factory=list)
    nullable_primary_keys: list[str] = field(default_factory=list)
    rate_limit_per_min: int = 180
    update_time: str = "18:00"
    update_delay_days: int = 0
    delay_in_trading_days: bool = False
    date_columns: list[str] = field(default_factory=list)
    required_columns: list[str] = field(default_factory=list)
    units: dict[str, str] = field(default_factory=dict)
    max_range_days: int | None = None
    request_window_days: int | None = None
    pagination_required: bool = True
    max_rows_per_request: int | None = None
    quality_profile: str = "generic"
    request_fields: str | None = None
