"""核心观察池实时监控协调器。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl

from stock_analytics.realtime.baseline import RealtimeBaseline, build_realtime_baselines
from stock_analytics.realtime.cache import RealtimeSnapshotCache
from stock_analytics.realtime.report import build_report_frame
from stock_core.contracts import MarketDataCatalog
from stock_core.exceptions import DataFetchError
from stock_data.fetcher.realtime.base import BaseRealtimeFetcher, RealtimeQuote
from stock_data.fetcher.realtime.recorder import RealtimeSnapshotRecorder

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class RealtimeMonitor:
    """协调实时快照、缓存、Curated 基准和监控指标。"""

    def __init__(
        self,
        fetcher: BaseRealtimeFetcher,
        catalog: MarketDataCatalog,
        *,
        cache: RealtimeSnapshotCache | None = None,
        recorder: RealtimeSnapshotRecorder | None = None,
        max_amount_ratio: float = 100.0,
    ) -> None:
        self.fetcher = fetcher
        self.catalog = catalog
        self.cache = cache or RealtimeSnapshotCache()
        self.recorder = recorder
        self.max_amount_ratio = max(1.0, max_amount_ratio)
        self._baseline_cache: dict[
            tuple[date, tuple[tuple[str, tuple[str, ...]], ...]], dict[str, RealtimeBaseline]
        ] = {}

    def run(
        self,
        symbols_by_dataset: Mapping[str, Sequence[str]],
        *,
        as_of_date: date | None = None,
        now: datetime | None = None,
    ) -> pl.DataFrame:
        """执行一次核心观察池实时体检。"""
        current_time = now or datetime.now(_SHANGHAI_TZ)
        symbols = _flatten_symbols(symbols_by_dataset)
        quotes = self._fetch_quotes(symbols, current_time)
        if self.recorder is not None:
            self.recorder.append(quotes, now=current_time)
        effective_as_of = as_of_date or current_time.date()
        baseline_key = (
            effective_as_of,
            tuple((dataset, tuple(symbols)) for dataset, symbols in symbols_by_dataset.items()),
        )
        if baseline_key not in self._baseline_cache:
            self._baseline_cache[baseline_key] = build_realtime_baselines(
                self.catalog,
                symbols_by_dataset,
                as_of_date=effective_as_of,
            )
        return build_report_frame(
            quotes,
            self._baseline_cache[baseline_key],
            self.cache,
            current_time,
            max_amount_ratio=self.max_amount_ratio,
        )

    def _fetch_quotes(
        self,
        symbols: Sequence[str],
        now: datetime,
    ) -> tuple[RealtimeQuote, ...]:
        try:
            quotes = self.fetcher.fetch_quotes(symbols)
            self.cache.put_many(quotes)
            resolved: list[RealtimeQuote] = []
            for quote in quotes:
                if quote.status != "missing":
                    resolved.append(quote)
                    continue
                cached = self.cache.lookup(self.fetcher.source, quote.symbol, now=now)
                resolved.append(cached.quote if cached is not None else quote)
            return tuple(resolved)
        except DataFetchError:
            fallback: list[RealtimeQuote] = []
            for symbol in symbols:
                cached = self.cache.lookup(self.fetcher.source, symbol, now=now)
                if cached is not None:
                    fallback.append(cached.quote)
                else:
                    fallback.append(
                        RealtimeQuote(
                            symbol=symbol,
                            provider_symbol="",
                            source=self.fetcher.source,
                            received_at=now,
                            status="missing",
                        )
                    )
            if any(quote.status != "missing" for quote in fallback):
                return tuple(fallback)
            raise


def _flatten_symbols(symbols_by_dataset: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(symbol).strip()
            for symbols in symbols_by_dataset.values()
            for symbol in symbols
            if str(symbol).strip()
        )
    )


__all__ = ["RealtimeBaseline", "RealtimeMonitor", "build_realtime_baselines"]
