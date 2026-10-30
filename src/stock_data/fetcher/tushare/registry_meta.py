"""TuShare 接口元数据 dataclass 定义。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EndpointMeta:
    """TuShare 接口元数据描述。"""

    api_name: str
    description: str
    market: str = "CN"
    frequency: str = "daily"  # daily, monthly, quarterly, event
    query_mode: str = (
        "trade_date"  # trade_date, ann_date, float_date, symbol, date, month, quarter, period
    )
    symbol_query_mode: str | None = None
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
    sync_lookback_days: int | None = None
    per_symbol_windowed: bool = False
    pagination_required: bool = True
    max_rows_per_request: int | None = None
    quality_profile: str = "generic"
    request_fields: str | None = None
    fetch_mode: str | None = None
    partitioned: bool | None = None
    is_single_sync: bool | None = None
    dataset: str | None = None
    required_pool: str | None = None
    period_query_variants: tuple[tuple[tuple[str, str], ...], ...] = ()
    period_query_variant_columns: dict[str, str] = field(default_factory=dict)
    replace_raw_on_refresh: bool = False
    # 源端标识列改名映射（如 fund_portfolio 的 ts_code 是基金代码，须与 symbol=被持有股票代码 并存）
    identity_renames: dict[str, str] = field(default_factory=dict)
