"""增量同步目标日期解析。"""

from datetime import date, datetime, timedelta

from stock_data.pipeline.scheduler import DataUpdateScheduler


def _previous_month_start(target_date: date) -> date:
    """返回目标日前一个完整月的起始日。"""
    if target_date.month == 1:
        return date(target_date.year - 1, 12, 1)
    return date(target_date.year, target_date.month - 1, 1)


def _previous_month_end(target_date: date) -> date:
    """返回目标日前一个完整月的月末日。"""
    return target_date.replace(day=1) - timedelta(days=1)


def _previous_quarter_start(target_date: date) -> date:
    """返回目标日前一个完整季度的起始日。"""
    current_quarter = (target_date.month - 1) // 3
    if current_quarter == 0:
        return date(target_date.year - 1, 10, 1)
    return date(target_date.year, (current_quarter - 1) * 3 + 1, 1)


def _quarter_end(target_date: date) -> date:
    """返回给定日期所在季度的报告期末。"""
    if target_date.month <= 3:
        return date(target_date.year, 3, 31)
    if target_date.month <= 6:
        return date(target_date.year, 6, 30)
    if target_date.month <= 9:
        return date(target_date.year, 9, 30)
    return date(target_date.year, 12, 31)


def _previous_quarter_end(target_date: date) -> date:
    """返回目标日前一个季度的报告期末。"""
    if target_date.month <= 3:
        return date(target_date.year - 1, 12, 31)
    if target_date.month <= 6:
        return date(target_date.year, 3, 31)
    if target_date.month <= 9:
        return date(target_date.year, 6, 30)
    return date(target_date.year, 9, 30)


def _latest_completed_quarter_end(target_date: date) -> date:
    """返回目标日已结束季度中最新的报告期末。"""
    quarter_end = _quarter_end(target_date)
    return quarter_end if quarter_end <= target_date else _previous_quarter_end(target_date)


def _latest_ready_period_end(
    data_source: str,
    endpoint: str,
    candidate: date,
    frequency: str,
    current_datetime: datetime | None,
) -> date | None:
    """回退到最近一个已过发布窗口的完整月/季。"""
    max_lookback = 24 if frequency == "monthly" else 12
    for _ in range(max_lookback):
        if DataUpdateScheduler.is_data_ready(
            endpoint=endpoint,
            target_date=candidate,
            current_datetime=current_datetime,
            data_source=data_source,
        ):
            return candidate
        previous = (
            _previous_month_end(candidate)
            if frequency == "monthly"
            else _previous_quarter_end(candidate)
        )
        if previous >= candidate:
            break
        candidate = previous
    return None


def next_report_period_end(watermark: date) -> date:
    """返回报告期水位之后的下一个自然季度末。"""
    return _quarter_end(watermark + timedelta(days=1))


def _previous_week_start(target_date: date) -> date:
    """返回目标日前一个完整自然周的周一。"""
    current_week_start = target_date - timedelta(days=target_date.weekday())
    return current_week_start - timedelta(days=7)


def _period_target_date(target_date: date, frequency: str) -> date:
    """将默认同步目标对齐到已结束的统计期间。"""
    if frequency == "monthly":
        return _previous_month_start(target_date)
    if frequency == "quarterly":
        return _previous_quarter_start(target_date)
    if frequency == "weekly":
        return _previous_week_start(target_date)
    return target_date


def next_watermark_date(watermark: date, frequency: str) -> date:
    """返回给定统计期间水位之后的最小请求起始日期。"""
    if frequency == "monthly":
        if watermark.month == 12:
            return date(watermark.year + 1, 1, 1)
        return date(watermark.year, watermark.month + 1, 1)
    if frequency == "quarterly":
        if watermark.month >= 10:
            return date(watermark.year + 1, 1, 1)
        return date(watermark.year, watermark.month + 3, 1)
    if frequency == "weekly":
        return watermark + timedelta(days=7)
    return watermark + timedelta(days=1)


def normalize_watermark_date(watermark: date, frequency: str) -> date:
    """将实际发布日期归一到对应统计期间，避免低频接口重复补拉。"""
    if frequency == "monthly":
        return watermark.replace(day=1)
    if frequency == "quarterly":
        return watermark.replace(month=((watermark.month - 1) // 3) * 3 + 1, day=1)
    if frequency == "weekly":
        return watermark - timedelta(days=watermark.weekday())
    return watermark


def resolve_sync_target_date(
    data_source: str,
    endpoint: str,
    target_date: date,
    target_date_is_explicit: bool,
    current_datetime: datetime | None = None,
) -> date | None:
    """解析默认同步时当前已发布且已过窗口的最近数据日或报告期。"""
    try:
        from stock_data.core.task_resolution import resolve_task

        task = resolve_task(data_source, endpoint)
        if task.fetch_mode == "per_period" and task.frequency == "quarterly":
            period_candidate = _latest_completed_quarter_end(target_date)
            if not target_date_is_explicit:
                return _latest_ready_period_end(
                    data_source, endpoint, period_candidate, task.frequency, current_datetime
                )
            return period_candidate
        if (
            not target_date_is_explicit
            and task.fetch_mode == "per_period"
            and task.frequency == "monthly"
        ):
            return _latest_ready_period_end(
                data_source,
                endpoint,
                _previous_month_end(target_date),
                task.frequency,
                current_datetime,
            )
        if (
            not target_date_is_explicit
            and task.frequency == "monthly"
            and task.query_mode == "trade_date"
        ):
            return _previous_month_end(target_date)
    except Exception:
        pass
    if target_date_is_explicit:
        return target_date
    meta = DataUpdateScheduler.get_endpoint_update_meta(data_source, endpoint)
    period_target = _period_target_date(target_date, meta.frequency)
    if meta.frequency != "daily":
        return period_target
    if data_source == "fred":
        source_now = current_datetime or datetime.now(meta.timezone)
        if source_now.tzinfo is None:
            source_now = source_now.replace(tzinfo=meta.timezone)
        else:
            source_now = source_now.astimezone(meta.timezone)
        candidate = source_now.date()
        for _ in range(32):
            if DataUpdateScheduler.is_data_ready(
                endpoint=endpoint,
                target_date=candidate,
                current_datetime=source_now,
                data_source=data_source,
            ):
                return candidate
            candidate -= timedelta(days=1)
        return None
    if data_source == "tushare" and endpoint == "us_stock_daily_bar":
        import exchange_calendars as xcals

        sessions = xcals.get_calendar("XNYS").sessions_in_range(
            (target_date - timedelta(days=14)).isoformat(), target_date.isoformat()
        )
        candidates = [session.date() for session in sessions if session.date() < target_date]
        return candidates[-1] if candidates else None
    trading_date = DataUpdateScheduler.get_latest_trading_date(
        target_date, data_source=data_source, strictly_before=meta.delay_in_trading_days
    )
    if trading_date is None:
        if meta.delay_in_trading_days:
            return None
        candidate = target_date
    else:
        candidate = trading_date
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
