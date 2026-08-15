"""指标滚动窗口辅助。"""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class MetricWindow:
    """指标计算日期窗口。"""

    start_date: date
    end_date: date
    lookback_days: int


def build_calendar_lookback_window(end_date: date, lookback_days: int) -> MetricWindow:
    """按自然日回看天数构造窗口。"""
    return MetricWindow(
        start_date=end_date - timedelta(days=lookback_days),
        end_date=end_date,
        lookback_days=lookback_days,
    )


def build_lookback_window(end_date: date, lookback_days: int) -> MetricWindow:
    """兼容旧入口，按自然日回看天数构造窗口。"""
    return build_calendar_lookback_window(end_date, lookback_days)
