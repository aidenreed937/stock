"""数据任务的稳定领域类型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskSpec:
    """一个公开项目任务到一个上游 API 的固定映射与调度行为契约。"""

    task_name: str
    provider: str
    api_name: str
    dataset: str
    frequency: str = "daily"
    quality_profile: str = "generic"
    partitioned: bool = True
    fetch_mode: str = "per_day"  # "per_day" | "per_symbol" | "per_period"
    is_single_sync: bool = False
    required_pool: str | None = None
    primary_keys: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()
    required_columns: tuple[str, ...] = ()
    units: dict[str, str] = field(default_factory=dict)
    query_mode: str = "trade_date"
    update_time: str = "18:00"
    update_delay_days: int = 0
    delay_in_trading_days: bool = False
    request_window_days: int | None = None
    sync_lookback_days: int | None = None
    max_rows_per_request: int | None = None
    max_codes_per_request: int | None = None
    request_fields: str | None = None
    refresh_current_period: bool = True
    watermark_column: str | None = None
    sync_policy: str = "incremental"
    max_increment_days: int | None = None
    identity_renames: dict[str, str] = field(default_factory=dict)


__all__ = ["TaskSpec"]
