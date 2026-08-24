"""指标滚动窗口与计算器通用辅助工具。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from stock_analytics.metrics.context import MetricContext

_CALENDAR_BUFFER_MULTIPLIER: int = 3


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


_STRING_KEY_COLUMNS = frozenset({"symbol", "industry_code", "industry_name", "underlying_symbol"})


def empty_metric_frame(columns: tuple[str, ...]) -> pl.DataFrame:
    """构造指标空 Schema DataFrame。"""
    return pl.DataFrame(
        schema={
            column: pl.Date
            if column == "trade_date"
            else pl.String
            if column in _STRING_KEY_COLUMNS
            else pl.Float64
            for column in columns
        }
    )


def first_column(df: pl.DataFrame, candidates: tuple[str, ...], dataset: str = "dataset") -> str:
    """匹配首个可用字段，若无匹配则抛出 ValueError。"""
    for column in candidates:
        if column in df.columns:
            return column
    raise ValueError(f"{dataset} 缺少字段: {', '.join(candidates)}")


def load_start_date(
    context: MetricContext,
    max_window: int,
    buffer_multiplier: int = _CALENDAR_BUFFER_MULTIPLIER,
) -> date | None:
    """根据最大回看窗口与自然日乘数推导起算日期。"""
    end_date = context.resolve_end_date()
    if end_date is None:
        return context.start_date
    lookback_start = end_date - timedelta(days=max_window * buffer_multiplier)
    if context.start_date is None:
        return lookback_start
    return min(context.start_date, lookback_start)


__all__ = [
    "MetricWindow",
    "build_calendar_lookback_window",
    "empty_metric_frame",
    "first_column",
    "load_start_date",
]
