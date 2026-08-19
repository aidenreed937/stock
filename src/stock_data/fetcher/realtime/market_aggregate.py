"""A 股全市场低频聚合行情抓取器。"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel, ConfigDict, Field

from stock_core.exceptions import DataFetchError

MarketAggregateStatus = Literal["valid", "partial"]

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_DEFAULT_ENDPOINT = "https://82.push2.eastmoney.com/api/qt/clist/get"
_DEFAULT_MARKET_FILTER = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
_DEFAULT_FIELDS = "f2,f3,f6,f12,f20,f21"


class MarketAggregateSnapshot(BaseModel):
    """一次 A 股全市场聚合快照；不包含逐标的明细。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = "eastmoney"
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
        """返回快照所属日期；东方财富列表没有逐行撮合时间，回退接收日期。"""
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


class MarketAggregateFetcher(BaseMarketAggregateFetcher):
    """通过东方财富轻量列表接口抓取 A 股全市场聚合指标。"""

    source = "eastmoney"

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        endpoint: str = _DEFAULT_ENDPOINT,
        page_size: int = 100,
        max_pages: int = 100,
        timeout_seconds: float = 8.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.3,
        strong_move_threshold_pct: float = 5.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """初始化聚合客户端；默认每 100 条分页，避免单个超大响应。"""
        self.session = session or requests.Session()
        self.endpoint = endpoint
        self.page_size = min(100, max(1, page_size))
        self.max_pages = max(1, max_pages)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.strong_move_threshold_pct = max(0.01, strong_move_threshold_pct)
        self.clock = clock or (lambda: datetime.now(_SHANGHAI_TZ))

    def fetch_aggregate(self) -> MarketAggregateSnapshot:
        """分页抓取轻量字段后在内存中聚合，不返回逐标的行情明细。"""
        rows, reported_count = self._fetch_rows()
        received_at = self.clock()
        return _aggregate_rows(
            rows,
            reported_count=reported_count,
            received_at=received_at,
            source=self.source,
            strong_move_threshold_pct=self.strong_move_threshold_pct,
        )

    def _fetch_rows(self) -> tuple[list[Mapping[str, Any]], int]:
        rows: list[Mapping[str, Any]] = []
        reported_count = 0
        for page in range(1, self.max_pages + 1):
            payload = self._request_page(page)
            data = payload.get("data")
            if not isinstance(data, Mapping):
                raise DataFetchError("东方财富市场聚合响应缺少 data 对象")
            if page == 1:
                reported_count = _nonnegative_int(data.get("total"))
            diff = data.get("diff") or []
            if not isinstance(diff, list):
                raise DataFetchError("东方财富市场聚合响应的 diff 不是列表")
            page_rows = [row for row in diff if isinstance(row, Mapping)]
            rows.extend(page_rows)
            if not page_rows:
                break
            if reported_count and len(rows) >= reported_count:
                break
            if len(page_rows) < self.page_size:
                break

        if not rows:
            raise DataFetchError("东方财富市场聚合响应未返回 A 股标的")
        return rows, reported_count or len(rows)

    def _request_page(self, page: int) -> Mapping[str, Any]:
        params: dict[str, str | int] = {
            "pn": page,
            "pz": self.page_size,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f12",
            "fs": _DEFAULT_MARKET_FILTER,
            "fields": _DEFAULT_FIELDS,
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    self.endpoint,
                    params=params,
                    timeout=self.timeout_seconds,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://quote.eastmoney.com/",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, Mapping):
                    raise ValueError("响应 JSON 顶层不是对象")
                if payload.get("rc") not in (None, 0):
                    raise ValueError(f"响应返回 rc={payload.get('rc')}")
                return payload
            except (requests.RequestException, UnicodeError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
        raise DataFetchError(
            f"东方财富市场聚合请求失败: page={page}, attempts={self.max_retries + 1}, "
            f"error={last_error}"
        ) from last_error


def _aggregate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    reported_count: int,
    received_at: datetime,
    source: str,
    strong_move_threshold_pct: float,
) -> MarketAggregateSnapshot:
    changes = [_as_float(row.get("f3")) for row in rows]
    valid_changes = [value for value in changes if value is not None]
    amounts = [_as_nonnegative_float(row.get("f6")) for row in rows]
    valid_amounts = [value for value in amounts if value is not None]
    market_values = [_as_nonnegative_float(row.get("f20")) for row in rows]
    valid_market_values = [value for value in market_values if value is not None]
    free_float_values = [_as_nonnegative_float(row.get("f21")) for row in rows]
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
        received_at=received_at,
        reported_count=reported_count,
        returned_count=len(rows),
        priced_count=sum(_as_positive_float(row.get("f2")) is not None for row in rows),
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


def _nonnegative_int(value: object) -> int:
    number = _as_float(value)
    return int(number) if number is not None and number >= 0 else 0


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
]
