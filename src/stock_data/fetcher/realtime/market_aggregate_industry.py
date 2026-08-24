"""腾讯全市场聚合的行业维度切片（与全市场快照并列，独立于逐标的数据）。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from stock_data.fetcher.realtime.market_aggregate import MarketAggregateSnapshot

MarketAggregateStatus = Literal["valid", "partial"]


class IndustryBreadthRow(BaseModel):
    """单个行业的盘中聚合行（全市场摘要的行业切片，非逐标的明细）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    industry: str = Field(..., description="行业名称（本地 stock_basic.industry）")
    member_count: int = Field(ge=0, description="映射到该行业的标的数")
    priced_count: int = Field(ge=0, description="有价格的标的数")
    advance_count: int = Field(ge=0, description="上涨家数")
    decline_count: int = Field(ge=0, description="下跌家数")
    flat_count: int = Field(ge=0, description="平盘家数")
    advance_share: float | None = Field(default=None, ge=0, le=1, description="上涨占比")
    decline_share: float | None = Field(default=None, ge=0, le=1, description="下跌占比")
    advance_decline_ratio: float | None = Field(default=None, ge=0, description="涨跌比")
    strong_up_count: int = Field(ge=0, description="强势上涨家数")
    strong_down_count: int = Field(ge=0, description="强势下跌家数")
    median_pct_change: float | None = Field(default=None, description="中位涨跌幅 (%)")
    amount_total_yuan: float | None = Field(default=None, ge=0, description="行业成交额 (元)")
    weighted_pct_change: float | None = Field(default=None, description="成交额加权涨跌幅 (%)")


class IndustryBreadthSnapshot(BaseModel):
    """一次全市场聚合中的行业维度快照（与 MarketAggregateSnapshot 并列，独立落盘）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    quote_date: date
    quote_at: datetime | None = None
    received_at: datetime
    status: MarketAggregateStatus
    reported_count: int = Field(ge=0, description="全市场股票全集数")
    mapped_count: int = Field(ge=0, description="成功映射到行业的标的数")
    industry_count: int = Field(ge=0, description="有效行业数（含 min_members 过滤）")
    raw_industry_count: int = Field(ge=0, description="映射到的行业数（未过滤）")
    strong_move_threshold_pct: float = Field(gt=0, description="强势涨跌阈值 (%)")
    rows: tuple[IndustryBreadthRow, ...] = Field(default_factory=tuple, description="行业聚合行")

    @property
    def is_usable(self) -> bool:
        """判断行业快照是否至少有一个行业行。"""
        return bool(self.rows)


_UNKNOWN_INDUSTRY = "__UNKNOWN__"


def aggregate_industry_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    industry_map: Mapping[str, str],
    reported_count: int,
    received_at: datetime,
    quote_at: datetime | None,
    source: str,
    strong_move_threshold_pct: float,
    min_members: int,
) -> IndustryBreadthSnapshot:
    """按行业分组聚合涨跌广度、强弱与成交；未映射标的进入"未分类"。

    行业映射键为本地标准 symbol（如 ``600519.SH``），与行情行保留的
    symbol 保持一致；未知行业统一归入 ``__UNKNOWN__`` 占位。
    """
    epsilon = 1e-9
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    mapped_count = 0
    for row in rows:
        symbol = _as_str(row.get("symbol"))
        industry = _as_str(industry_map.get(symbol)) if symbol else None
        if industry is None:
            industry = _UNKNOWN_INDUSTRY
        else:
            mapped_count += 1
        grouped.setdefault(industry, []).append(row)

    industry_rows: list[IndustryBreadthRow] = []
    for industry, group_rows in grouped.items():
        member_count = len(group_rows)
        changes = [_as_float(item.get("change")) for item in group_rows]
        valid_changes = [value for value in changes if value is not None]
        amounts = [_as_nonnegative_float(item.get("amount")) for item in group_rows]
        valid_amounts = [value for value in amounts if value is not None]
        if industry != _UNKNOWN_INDUSTRY and member_count < min_members:
            continue

        advance_count = sum(value > epsilon for value in valid_changes)
        decline_count = sum(value < -epsilon for value in valid_changes)
        flat_count = len(valid_changes) - advance_count - decline_count
        strong_up_count = sum(value >= strong_move_threshold_pct for value in valid_changes)
        strong_down_count = sum(value <= -strong_move_threshold_pct for value in valid_changes)
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
        industry_rows.append(
            IndustryBreadthRow(
                industry=industry,
                member_count=member_count,
                priced_count=len(valid_changes),
                advance_count=advance_count,
                decline_count=decline_count,
                flat_count=flat_count,
                advance_share=_share(advance_count, len(valid_changes)),
                decline_share=_share(decline_count, len(valid_changes)),
                advance_decline_ratio=(
                    advance_count / decline_count if decline_count > 0 else None
                ),
                strong_up_count=strong_up_count,
                strong_down_count=strong_down_count,
                median_pct_change=_percentile(valid_changes, 0.50),
                amount_total_yuan=sum(valid_amounts) if valid_amounts else None,
                weighted_pct_change=weighted_pct_change,
            )
        )

    visible_rows = tuple(sorted(industry_rows, key=lambda row: row.member_count, reverse=True))
    raw_industry_count = len({key for key in grouped if key != _UNKNOWN_INDUSTRY})
    effective_industry_count = sum(row.industry != _UNKNOWN_INDUSTRY for row in visible_rows)
    return IndustryBreadthSnapshot(
        source=source,
        quote_date=(quote_at or received_at).date(),
        quote_at=quote_at,
        received_at=received_at,
        status="valid" if len(rows) >= reported_count else "partial",
        reported_count=reported_count,
        mapped_count=mapped_count,
        industry_count=effective_industry_count,
        raw_industry_count=raw_industry_count,
        strong_move_threshold_pct=strong_move_threshold_pct,
        rows=visible_rows,
    )


def empty_industry_snapshot(snapshot: MarketAggregateSnapshot) -> IndustryBreadthSnapshot:
    """构造与给定全市场快照同元数据的空行业快照（数据源不支持时降级）。"""
    return IndustryBreadthSnapshot(
        source=snapshot.source,
        quote_date=snapshot.quote_date,
        quote_at=snapshot.quote_at,
        received_at=snapshot.received_at,
        status=snapshot.status,
        reported_count=snapshot.reported_count,
        mapped_count=0,
        industry_count=0,
        raw_industry_count=0,
        strong_move_threshold_pct=snapshot.strong_up_threshold_pct,
    )


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


__all__ = [
    "IndustryBreadthRow",
    "IndustryBreadthSnapshot",
    "aggregate_industry_rows",
    "empty_industry_snapshot",
]
