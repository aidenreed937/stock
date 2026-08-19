"""实时快照的进程内缓存与失效判断。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from stock_data.fetcher.realtime.base import RealtimeQuote


class CacheFreshness(StrEnum):
    """快照缓存的新鲜度状态。"""

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class CachedQuote:
    """带缓存年龄和失效状态的实时快照。"""

    quote: RealtimeQuote
    age_seconds: float
    freshness: CacheFreshness


class RealtimeSnapshotCache:
    """按数据源、标准代码和行情日期隔离的内存快照缓存。"""

    def __init__(
        self,
        *,
        fresh_ttl_seconds: float = 2.0,
        max_age_seconds: float = 60.0,
    ) -> None:
        self.fresh_ttl_seconds = max(0.0, fresh_ttl_seconds)
        self.max_age_seconds = max(self.fresh_ttl_seconds, max_age_seconds)
        self._items: dict[tuple[str, str, date], RealtimeQuote] = {}

    def put(self, quote: RealtimeQuote) -> None:
        """写入一条快照；缺失快照不进入缓存。"""
        if not quote.is_valid:
            return
        key = (quote.source, quote.symbol, quote.quote_date)
        self._items[key] = quote

    def put_many(self, quotes: Sequence[RealtimeQuote]) -> None:
        """批量写入快照。"""
        for quote in quotes:
            self.put(quote)

    def lookup(
        self,
        source: str,
        symbol: str,
        *,
        now: datetime | None = None,
    ) -> CachedQuote | None:
        """查找当天快照；过期项仍返回以便报告明确显示 expired。"""
        current_time = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        candidates = [
            quote
            for (item_source, item_symbol, item_date), quote in self._items.items()
            if item_source == source and item_symbol == symbol and item_date == current_time.date()
        ]
        if not candidates:
            return None
        quote = max(candidates, key=lambda item: item.received_at)
        freshness_at = quote.quote_at or quote.received_at
        age_seconds = max(0.0, _datetime_delta_seconds(current_time, freshness_at))
        freshness = (
            CacheFreshness.FRESH
            if age_seconds <= self.fresh_ttl_seconds
            else CacheFreshness.STALE
            if age_seconds <= self.max_age_seconds
            else CacheFreshness.EXPIRED
        )
        return CachedQuote(quote=quote, age_seconds=age_seconds, freshness=freshness)

    def clear(self) -> None:
        """清空全部缓存。"""
        self._items.clear()

    def clear_source(self, source: str) -> None:
        """清除指定数据源的缓存。"""
        self._items = {key: quote for key, quote in self._items.items() if key[0] != source}


def _datetime_delta_seconds(left: datetime, right: datetime) -> float:
    """兼容测试中的 naive datetime 与生产中的带时区 datetime。"""
    if (left.tzinfo is None) != (right.tzinfo is None):
        if left.tzinfo is None:
            left = left.replace(tzinfo=right.tzinfo)
        else:
            right = right.replace(tzinfo=left.tzinfo)
    return (left - right).total_seconds()


__all__ = ["CacheFreshness", "CachedQuote", "RealtimeSnapshotCache"]
