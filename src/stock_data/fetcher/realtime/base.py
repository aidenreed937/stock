"""实时行情抓取的统一数据契约。"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RealtimeStatus = Literal["valid", "missing", "invalid"]

_SIX_DIGIT_CODE = re.compile(r"^\d{6}$")
_PROVIDER_CODE = re.compile(r"^(sh|sz)(\d{6})$", re.IGNORECASE)


def normalize_local_symbol(symbol: str) -> str:
    """将本地观察池代码规范为 ``######.EXCHANGE`` 形式。"""
    value = str(symbol).strip().upper()
    provider_match = _PROVIDER_CODE.fullmatch(value)
    if provider_match:
        exchange = "SH" if provider_match.group(1).lower() == "sh" else "SZ"
        return f"{provider_match.group(2)}.{exchange}"

    if "." in value:
        code, exchange = value.split(".", 1)
        if _SIX_DIGIT_CODE.fullmatch(code) and exchange in {"SH", "SZ", "CSI"}:
            return f"{code}.{exchange}"
        raise ValueError(f"不支持的 A 股实时标的代码: {symbol}")

    if not _SIX_DIGIT_CODE.fullmatch(value):
        raise ValueError(f"不支持的 A 股实时标的代码: {symbol}")
    exchange = "SH" if value[:1] in {"5", "6", "9"} or value[:2] in {"11", "13"} else "SZ"
    return f"{value}.{exchange}"


def to_tencent_symbol(symbol: str) -> str:
    """将本地代码转换为腾讯行情接口使用的 ``sh######`` / ``sz######``。"""
    local_symbol = normalize_local_symbol(symbol)
    code, exchange = local_symbol.split(".", 1)
    # CSI 指数在腾讯行情中使用 sh 前缀；本地 .CSI 后缀仍保留在标准代码中。
    market = "sz" if exchange == "SZ" else "sh"
    return f"{market}{code}"


class RealtimeQuote(BaseModel):
    """单个实时快照的标准化表示。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(description="本地标准标的代码")
    provider_symbol: str = Field(description="上游数据源标的代码")
    name: str = ""
    source: str = "tencent"
    quote_at: datetime | None = None
    received_at: datetime
    status: RealtimeStatus = "valid"
    price: float | None = None
    pre_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    bid_prices: tuple[float | None, ...] = (None, None, None, None, None)
    bid_volumes: tuple[float | None, ...] = (None, None, None, None, None)
    ask_prices: tuple[float | None, ...] = (None, None, None, None, None)
    ask_volumes: tuple[float | None, ...] = (None, None, None, None, None)

    @property
    def quote_date(self) -> date:
        """返回快照所属日期；缺少上游时间时回退到本地接收日期。"""
        return (self.quote_at or self.received_at).date()

    @property
    def is_valid(self) -> bool:
        """判断快照是否具备可计算的有效价格。"""
        return self.status == "valid" and self.price is not None and self.price > 0


class BaseRealtimeFetcher(ABC):
    """实时快照数据源的最小抽象接口。"""

    source = "unknown"

    @abstractmethod
    def fetch_quotes(self, symbols: Sequence[str]) -> tuple[RealtimeQuote, ...]:
        """批量获取实时快照。"""
        raise NotImplementedError


__all__ = [
    "BaseRealtimeFetcher",
    "RealtimeQuote",
    "RealtimeStatus",
    "normalize_local_symbol",
    "to_tencent_symbol",
]
