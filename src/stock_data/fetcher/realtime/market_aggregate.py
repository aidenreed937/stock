"""基于腾讯批量快照的 A 股全市场聚合行情抓取器。"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel, ConfigDict, Field

from stock_core.exceptions import DataFetchError
from stock_data.fetcher.realtime.base import (
    BaseRealtimeFetcher,
    RealtimeQuote,
    normalize_local_symbol,
)
from stock_data.fetcher.realtime.tencent import TencentRealtimeFetcher

MarketAggregateStatus = Literal["valid", "partial"]

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class MarketAggregateSnapshot(BaseModel):
    """一次 A 股全市场聚合快照；不包含逐标的明细。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = "tencent"
    scope: str = "a_share_full_market"
    status: MarketAggregateStatus
    quote_at: datetime | None = None
    received_at: datetime
    reported_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    priced_count: int = Field(ge=0)
    change_count: int = Field(ge=0)
    amount_count: int = Field(ge=0)
    market_cap_count: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    advance_count: int = Field(ge=0)
    decline_count: int = Field(ge=0)
    flat_count: int = Field(ge=0)
    advance_share: float | None = Field(default=None, ge=0, le=1)
    decline_share: float | None = Field(default=None, ge=0, le=1)
    advance_decline_ratio: float | None = Field(default=None, ge=0)
    strong_up_threshold_pct: float = Field(gt=0)
    strong_up_count: int = Field(ge=0)
    strong_down_count: int = Field(ge=0)
    strong_up_share: float | None = Field(default=None, ge=0, le=1)
    strong_down_share: float | None = Field(default=None, ge=0, le=1)
    median_pct_change: float | None = None
    pct_change_p25: float | None = None
    pct_change_p75: float | None = None
    weighted_pct_change: float | None = None
    amount_total_yuan: float | None = Field(default=None, ge=0)
    total_market_value_yuan: float | None = Field(default=None, ge=0)
    free_float_market_value_yuan: float | None = Field(default=None, ge=0)
    free_float_turnover_pct: float | None = Field(default=None, ge=0)
    amount_top_5pct_share: float | None = Field(default=None, ge=0, le=1)

    @property
    def quote_date(self) -> date:
        """返回快照所属日期；缺少腾讯撮合时间时回退接收日期。"""
        return (self.quote_at or self.received_at).date()

    @property
    def is_usable(self) -> bool:
        """判断快照是否至少具备一组可计算的涨跌数据。"""
        return self.status in {"valid", "partial"} and self.change_count > 0


class BaseMarketAggregateFetcher(ABC):
    """市场聚合数据源的最小接口。"""

    source = "unknown"

    @abstractmethod
    def fetch_aggregate(self) -> MarketAggregateSnapshot:
        """获取一次市场级聚合快照。"""
        raise NotImplementedError


class TencentMarketAggregateFetcher(BaseMarketAggregateFetcher):
    """读取本地股票全集，并通过腾讯接口分批获取实时快照后聚合。"""

    source = "tencent"

    def __init__(
        self,
        symbols: Sequence[str] = (),
        session: requests.Session | None = None,
        *,
        quote_fetcher: BaseRealtimeFetcher | None = None,
        batch_size: int = 100,
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.2,
        strong_move_threshold_pct: float = 5.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """初始化客户端；股票全集由管线从本地 stock_basic 提供。"""
        self.symbols = _normalize_symbols(symbols)
        self.batch_size = max(1, batch_size)
        self.quote_fetcher = quote_fetcher or TencentRealtimeFetcher(
            session=session,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        self.strong_move_threshold_pct = max(0.01, strong_move_threshold_pct)
        self.clock = clock or (lambda: datetime.now(_SHANGHAI_TZ))

    def fetch_aggregate(self) -> MarketAggregateSnapshot:
        """分批抓取腾讯快照并在内存中聚合，不返回逐标的行情明细。"""
        if not self.symbols:
            raise DataFetchError(
                "腾讯全市场聚合需要本地 stock_basic 股票全集，请先运行："
                "make backfill ENDPOINT=stock_basic"
            )

        quotes, failures = self._fetch_quotes()
        if not quotes:
            if failures:
                last_error = failures[-1]
                raise DataFetchError(
                    f"腾讯全市场聚合所有批次请求失败: batches={len(failures)}, error={last_error}"
                ) from last_error
            raise DataFetchError("腾讯全市场聚合未返回任何股票快照")

        received_at = self.clock()
        quote_times = [quote.quote_at for quote in quotes if quote.quote_at is not None]
        return _aggregate_rows(
            [_quote_to_row(quote) for quote in quotes],
            reported_count=len(self.symbols),
            received_at=received_at,
            quote_at=max(quote_times) if quote_times else None,
            source=self.source,
            strong_move_threshold_pct=self.strong_move_threshold_pct,
        )

    def _fetch_quotes(self) -> tuple[list[RealtimeQuote], list[DataFetchError]]:
        quotes: list[RealtimeQuote] = []
        failures: list[DataFetchError] = []
        for start in range(0, len(self.symbols), self.batch_size):
            batch = self.symbols[start : start + self.batch_size]
            try:
                batch_quotes = self.quote_fetcher.fetch_quotes(batch)
            except DataFetchError as exc:
                failures.append(exc)
                continue
            quotes.extend(quote for quote in batch_quotes if quote.status != "missing")
        return quotes, failures


# 保留原有公共名称，避免调用方因为数据源替换而需要改动导入路径。
MarketAggregateFetcher = TencentMarketAggregateFetcher


def _normalize_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        local_symbol = normalize_local_symbol(symbol)
        if local_symbol not in seen:
            normalized.append(local_symbol)
            seen.add(local_symbol)
    return tuple(normalized)


def _quote_to_row(quote: RealtimeQuote) -> dict[str, float | None]:
    return {
        "price": quote.price,
        "change": _quote_pct_change(quote),
        "amount": quote.amount,
        "total_market_value_yuan": quote.total_market_value_yuan,
        "free_float_market_value_yuan": quote.free_float_market_value_yuan,
    }


def _quote_pct_change(quote: RealtimeQuote) -> float | None:
    if quote.price is None or quote.pre_close is None or quote.price <= 0 or quote.pre_close <= 0:
        return None
    return (quote.price - quote.pre_close) / quote.pre_close * 100


def _aggregate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    reported_count: int,
    received_at: datetime,
    quote_at: datetime | None,
    source: str,
    strong_move_threshold_pct: float,
) -> MarketAggregateSnapshot:
    changes = [_as_float(row.get("change")) for row in rows]
    valid_changes = [value for value in changes if value is not None]
    amounts = [_as_nonnegative_float(row.get("amount")) for row in rows]
    valid_amounts = [value for value in amounts if value is not None]
    market_values = [_as_nonnegative_float(row.get("total_market_value_yuan")) for row in rows]
    valid_market_values = [value for value in market_values if value is not None]
    free_float_values = [
        _as_nonnegative_float(row.get("free_float_market_value_yuan")) for row in rows
    ]
    valid_free_float_values = [value for value in free_float_values if value is not None]

    epsilon = 1e-9
    advance_count = sum(value > epsilon for value in valid_changes)
    decline_count = sum(value < -epsilon for value in valid_changes)
    flat_count = len(valid_changes) - advance_count - decline_count
    strong_up_count = sum(value >= strong_move_threshold_pct for value in valid_changes)
    strong_down_count = sum(value <= -strong_move_threshold_pct for value in valid_changes)
    amount_total = sum(valid_amounts) if valid_amounts else None
    free_float_market_value = sum(valid_free_float_values) if valid_free_float_values else None

    weighted_pairs = [
        (change, amount)
        for change, amount in zip(changes, amounts, strict=True)
        if change is not None and amount is not None and amount > 0
    ]
    weighted_amount = sum(amount for _, amount in weighted_pairs)
    weighted_pct_change = (
        sum(change * amount for change, amount in weighted_pairs) / weighted_amount
        if weighted_amount > 0
        else None
    )
    coverage_ratio = min(1.0, len(rows) / reported_count) if reported_count > 0 else 1.0

    return MarketAggregateSnapshot(
        source=source,
        status="valid" if len(rows) >= reported_count else "partial",
        quote_at=quote_at,
        received_at=received_at,
        reported_count=reported_count,
        returned_count=len(rows),
        priced_count=sum(_as_positive_float(row.get("price")) is not None for row in rows),
        change_count=len(valid_changes),
        amount_count=len(valid_amounts),
        market_cap_count=len(valid_market_values),
        coverage_ratio=coverage_ratio,
        advance_count=advance_count,
        decline_count=decline_count,
        flat_count=flat_count,
        advance_share=_share(advance_count, len(valid_changes)),
        decline_share=_share(decline_count, len(valid_changes)),
        advance_decline_ratio=(advance_count / decline_count if decline_count > 0 else None),
        strong_up_threshold_pct=strong_move_threshold_pct,
        strong_up_count=strong_up_count,
        strong_down_count=strong_down_count,
        strong_up_share=_share(strong_up_count, len(valid_changes)),
        strong_down_share=_share(strong_down_count, len(valid_changes)),
        median_pct_change=_percentile(valid_changes, 0.50),
        pct_change_p25=_percentile(valid_changes, 0.25),
        pct_change_p75=_percentile(valid_changes, 0.75),
        weighted_pct_change=weighted_pct_change,
        amount_total_yuan=amount_total,
        total_market_value_yuan=(sum(valid_market_values) if valid_market_values else None),
        free_float_market_value_yuan=free_float_market_value,
        free_float_turnover_pct=(
            amount_total / free_float_market_value * 100
            if amount_total is not None and free_float_market_value and free_float_market_value > 0
            else None
        ),
        amount_top_5pct_share=_top_amount_share(valid_amounts),
    )


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_positive_float(value: object) -> float | None:
    number = _as_float(value)
    return number if number is not None and number > 0 else None


def _as_nonnegative_float(value: object) -> float | None:
    number = _as_float(value)
    return number if number is not None and number >= 0 else None


def _share(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _top_amount_share(amounts: Sequence[float]) -> float | None:
    positive = sorted((amount for amount in amounts if amount > 0), reverse=True)
    total = sum(positive)
    if not positive or total <= 0:
        return None
    top_count = max(1, math.ceil(len(positive) * 0.05))
    return sum(positive[:top_count]) / total


__all__ = [
    "BaseMarketAggregateFetcher",
    "MarketAggregateFetcher",
    "MarketAggregateSnapshot",
    "MarketAggregateStatus",
    "TencentMarketAggregateFetcher",
]
