"""腾讯 ``qt.gtimg.cn`` 实时行情适配器。"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from stock_core.exceptions import DataFetchError
from stock_data.fetcher.realtime.base import (
    BaseRealtimeFetcher,
    RealtimeQuote,
    RealtimeStatus,
    normalize_local_symbol,
    to_tencent_symbol,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_RESPONSE_ROW = re.compile(
    r'v_(?P<provider>(?:sh|sz)\d{6})="(?P<body>.*?)";', re.IGNORECASE | re.DOTALL
)
_DEFAULT_ENDPOINT = "https://qt.gtimg.cn/q="


def _float_or_none(value: str | None) -> float | None:
    """将上游空字符串、异常数字转换为可审计的空值。"""
    if value is None:
        return None
    clean = value.strip()
    if not clean or clean in {"-", "--", "N/A", "nan", "NaN"}:
        return None
    try:
        number = float(clean)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _parse_quote_time(value: str | None) -> datetime | None:
    """解析腾讯返回的 ``YYYYMMDDHHMMSS`` 时间戳。"""
    if not value or len(value.strip()) < 14:
        return None
    try:
        return datetime.strptime(value.strip()[:14], "%Y%m%d%H%M%S").replace(tzinfo=_SHANGHAI_TZ)
    except ValueError:
        return None


def _parse_amount(parts: list[str]) -> float | None:
    """从腾讯 ``价格/手数/成交额`` 聚合字段提取人民币成交额。"""
    if len(parts) > 35:
        aggregate = parts[35].split("/")
        if len(aggregate) >= 3:
            amount = _float_or_none(aggregate[2])
            if amount is not None:
                return amount
    if len(parts) > 37:
        fallback = _float_or_none(parts[37])
        return fallback * 10000 if fallback is not None else None
    return None


def _parse_market_value(parts: list[str], index: int) -> float | None:
    """解析腾讯响应中以亿元表示的市值字段并统一换算为元。"""
    value = _float_or_none(parts[index] if len(parts) > index else None)
    return value * 100_000_000 if value is not None and value >= 0 else None


def _parse_row(
    provider_symbol: str,
    body: str,
    local_symbol: str,
    received_at: datetime,
) -> RealtimeQuote:
    """解析单行腾讯 ``~`` 分隔快照。"""
    parts = body.split("~")
    price = _float_or_none(parts[3] if len(parts) > 3 else None)
    pre_close = _float_or_none(parts[4] if len(parts) > 4 else None)
    status: RealtimeStatus = (
        "valid" if price is not None and price > 0 and pre_close is not None else "invalid"
    )

    bid_prices = tuple(
        _float_or_none(parts[index]) if len(parts) > index else None
        for index in (9, 11, 13, 15, 17)
    )
    bid_volumes = tuple(
        _float_or_none(parts[index]) if len(parts) > index else None
        for index in (10, 12, 14, 16, 18)
    )
    ask_prices = tuple(
        _float_or_none(parts[index]) if len(parts) > index else None
        for index in (19, 21, 23, 25, 27)
    )
    ask_volumes = tuple(
        _float_or_none(parts[index]) if len(parts) > index else None
        for index in (20, 22, 24, 26, 28)
    )
    raw_volume = _float_or_none(parts[36] if len(parts) > 36 else None)

    return RealtimeQuote(
        symbol=local_symbol,
        provider_symbol=provider_symbol.lower(),
        name=parts[1].strip() if len(parts) > 1 else "",
        source="tencent",
        quote_at=_parse_quote_time(parts[30] if len(parts) > 30 else None),
        received_at=received_at,
        status=status,
        price=price,
        pre_close=pre_close,
        open=_float_or_none(parts[5] if len(parts) > 5 else None),
        high=_float_or_none(parts[33] if len(parts) > 33 else None),
        low=_float_or_none(parts[34] if len(parts) > 34 else None),
        # 腾讯接口的 volume 字段单位为手；Curated 契约统一使用股。
        volume=raw_volume * 100 if raw_volume is not None else None,
        amount=_parse_amount(parts),
        # 腾讯公共行情字段 44/45 分别为流通市值/总市值，单位为亿元。
        free_float_market_value_yuan=_parse_market_value(parts, 44),
        total_market_value_yuan=_parse_market_value(parts, 45),
        bid_prices=bid_prices,
        bid_volumes=bid_volumes,
        ask_prices=ask_prices,
        ask_volumes=ask_volumes,
    )


class TencentRealtimeFetcher(BaseRealtimeFetcher):
    """通过腾讯公共行情接口批量获取 A 股实时快照。"""

    source = "tencent"

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.2,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """初始化客户端；重试次数不包含首次请求。"""
        self.session = session or requests.Session()
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.clock = clock or (lambda: datetime.now(_SHANGHAI_TZ))

    def fetch_quotes(self, symbols: Sequence[str]) -> tuple[RealtimeQuote, ...]:
        """批量请求观察池快照，并为未返回的标的生成 missing 状态。"""
        requested: list[tuple[str, str]] = []
        seen: set[str] = set()
        for symbol in symbols:
            local_symbol = normalize_local_symbol(symbol)
            provider_symbol = to_tencent_symbol(local_symbol)
            if local_symbol not in seen:
                requested.append((local_symbol, provider_symbol))
                seen.add(local_symbol)
        if not requested:
            return ()

        rows = self._request_rows([provider for _, provider in requested])
        received_at = self.clock()
        result: list[RealtimeQuote] = []
        for local_symbol, provider_symbol in requested:
            body = rows.get(provider_symbol)
            if body is None:
                result.append(
                    RealtimeQuote(
                        symbol=local_symbol,
                        provider_symbol=provider_symbol,
                        source=self.source,
                        received_at=received_at,
                        status="missing",
                    )
                )
            else:
                result.append(_parse_row(provider_symbol, body, local_symbol, received_at))
        return tuple(result)

    def _request_rows(self, provider_symbols: list[str]) -> dict[str, str]:
        url = f"{self.endpoint}{','.join(provider_symbols)}"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                response.raise_for_status()
                return self._parse_response(response.content)
            except (requests.RequestException, UnicodeError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
        raise DataFetchError(
            f"腾讯实时行情请求失败: symbols={provider_symbols}, attempts={self.max_retries + 1}, "
            f"error={last_error}"
        ) from last_error

    @staticmethod
    def _parse_response(payload: bytes) -> dict[str, str]:
        text = payload.decode("gb18030", errors="replace")
        rows = {
            match.group("provider").lower(): match.group("body")
            for match in _RESPONSE_ROW.finditer(text)
        }
        if not rows:
            raise ValueError("腾讯实时行情响应未包含有效快照行")
        return rows


__all__ = ["TencentRealtimeFetcher"]
