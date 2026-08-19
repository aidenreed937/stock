"""RAW 回填日期与业务期间缺口计算。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import polars as pl


def date_key(value: object) -> str:
    """将日期列中的紧凑格式和 ISO 格式统一为 YYYY-MM-DD。"""
    text = str(value)
    compact = text.replace("-", "").replace("/", "")
    if len(compact) >= 8 and compact[:8].isdigit():
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
    return text[:10]


def period_key(value: object, frequency: str) -> str:
    """将月频/季频业务日期转换为可比较的业务期间。"""
    text = str(value)
    compact = text.replace("-", "").replace("/", "")
    if frequency == "quarterly":
        if "Q" in text.upper():
            year, quarter = text.upper().split("Q", 1)
            if year.isdigit() and quarter[:1] in {"1", "2", "3", "4"}:
                return f"{int(year)}Q{quarter[0]}"
        if compact[:8].isdigit() or compact[:6].isdigit():
            month = int(compact[4:6])
            return f"{compact[:4]}Q{(month - 1) // 3 + 1}"
    if frequency == "monthly" and compact[:6].isdigit():
        return f"{compact[:4]}-{compact[4:6]}"
    return date_key(value)


def boundary_period(value: date, frequency: str) -> str:
    """将请求边界转换为与源端业务期间一致的格式。"""
    if frequency == "quarterly":
        return f"{value.year}Q{(value.month - 1) // 3 + 1}"
    if frequency == "monthly":
        return f"{value.year:04d}-{value.month:02d}"
    return str(value)


def expected_coverage(
    start: date,
    end: date,
    frequency: str,
    data_source: str,
    source_gaps: Iterable[object],
) -> tuple[list[str], list[str], set[str], set[str], str | None]:
    """返回回填区间的预期日期/期间、豁免缺口与交易日历错误。"""
    gap_dates = {date_key(value) for value in source_gaps}
    gap_periods = {period_key(value, frequency) for value in source_gaps}
    if frequency in {"monthly", "quarterly"}:
        return [], _expected_periods(start, end, frequency), gap_dates, gap_periods, None

    from stock_data.pipeline.scheduler import DataUpdateScheduler

    trading_days = DataUpdateScheduler.get_trading_days(start, end, data_source=data_source)
    if not trading_days:
        return (
            [],
            [],
            gap_dates,
            gap_periods,
            f"[{data_source}] 无法取得 {start} ~ {end} 的可信交易日历，拒绝按工作日推算",
        )
    return [str(trading_day) for trading_day in trading_days], [], gap_dates, gap_periods, None


def frame_coverage(frame: pl.DataFrame, frequency: str) -> tuple[set[str], set[str]]:
    """提取一张源表的日期与业务期间集合。"""
    date_col = next(
        (
            column
            for column in ("trade_date", "date", "end_date", "month", "quarter")
            if column in frame.columns
        ),
        None,
    )
    if date_col is None:
        return set(), set()
    values = frame[date_col].drop_nulls().unique().to_list()
    return (
        {date_key(value) for value in values},
        {period_key(value, frequency) for value in values},
    )


def raw_gap_status(
    expected_dates: list[str],
    expected_periods: list[str],
    raw_dates: set[str],
    raw_periods: set[str],
    gap_dates: set[str],
    gap_periods: set[str],
    frequency: str,
    calendar_error: str | None,
    has_range: bool,
) -> tuple[list[str] | None, list[str] | None, bool | None]:
    """计算 RAW 独立缺口报告。"""
    if not has_range:
        return None, None, True
    if frequency in {"monthly", "quarterly"}:
        missing = [
            period
            for period in expected_periods
            if period not in raw_periods and period not in gap_periods
        ]
        return [], missing, not missing
    missing = [day for day in expected_dates if day not in raw_dates and day not in gap_dates]
    return missing, [], calendar_error is None and not missing


def _expected_periods(start: date, end: date, frequency: str) -> list[str]:
    if frequency == "monthly":
        current = date(start.year, start.month, 1)
        last = date(end.year, end.month, 1)
        periods: list[str] = []
        while current <= last:
            periods.append(boundary_period(current, frequency))
            current = (
                date(current.year + 1, 1, 1)
                if current.month == 12
                else date(current.year, current.month + 1, 1)
            )
        return periods
    if frequency == "quarterly":
        year, quarter = start.year, (start.month - 1) // 3 + 1
        end_period = (end.year, (end.month - 1) // 3 + 1)
        quarter_periods: list[str] = []
        while (year, quarter) <= end_period:
            quarter_periods.append(f"{year}Q{quarter}")
            if quarter == 4:
                year, quarter = year + 1, 1
            else:
                quarter += 1
        return quarter_periods
    return []
