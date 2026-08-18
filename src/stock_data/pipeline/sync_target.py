"""增量同步目标交易日解析。"""

from datetime import date, datetime

from stock_data.pipeline.scheduler import DataUpdateScheduler


def resolve_sync_target_date(
    data_source: str,
    endpoint: str,
    target_date: date,
    target_date_is_explicit: bool,
    current_datetime: datetime | None = None,
) -> date | None:
    """解析默认同步时当前已发布且已过窗口的最近交易日。"""
    if target_date_is_explicit:
        return target_date
    meta = DataUpdateScheduler.get_endpoint_update_meta(data_source, endpoint)
    if meta.frequency != "daily":
        return target_date
    candidate = DataUpdateScheduler.get_latest_trading_date(
        target_date, data_source=data_source, strictly_before=meta.delay_in_trading_days
    )
    if candidate is None:
        if meta.delay_in_trading_days:
            return None
        candidate = target_date
    while not DataUpdateScheduler.is_data_ready(
        endpoint=endpoint,
        target_date=candidate,
        current_datetime=current_datetime,
        data_source=data_source,
    ):
        previous = DataUpdateScheduler.get_latest_trading_date(
            candidate, data_source=data_source, strictly_before=True
        )
        if previous is None:
            break
        candidate = previous
    return candidate
