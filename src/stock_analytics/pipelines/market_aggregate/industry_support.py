"""全市场聚合管线的行业维度辅助：空快照构造与事实表序列化。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from stock_data.fetcher.realtime.market_aggregate import MarketAggregateSnapshot
    from stock_data.fetcher.realtime.market_aggregate_industry import (
        IndustryBreadthSnapshot,
    )


def empty_industry_snapshot(snapshot: MarketAggregateSnapshot) -> IndustryBreadthSnapshot:
    """构造与全市场快照同元数据的空行业快照。"""
    from stock_data.fetcher.realtime.market_aggregate_industry import (
        empty_industry_snapshot as _empty_industry_snapshot,
    )

    return _empty_industry_snapshot(snapshot)


def industry_snapshot_to_frame(
    snapshot: IndustryBreadthSnapshot,
) -> pl.DataFrame:
    """将行业快照序列化为事实表，空快照返回空 DataFrame（仅保留通用列）。"""
    schema = {
        "quote_date": pl.Date,
        "source": pl.Utf8,
        "status": pl.Utf8,
        "mapped_count": pl.Int64,
        "industry_count": pl.Int64,
        "industry": pl.Utf8,
        "member_count": pl.Int64,
        "priced_count": pl.Int64,
        "advance_count": pl.Int64,
        "decline_count": pl.Int64,
        "flat_count": pl.Int64,
        "advance_share": pl.Float64,
        "decline_share": pl.Float64,
        "advance_decline_ratio": pl.Float64,
        "strong_up_count": pl.Int64,
        "strong_down_count": pl.Int64,
        "median_pct_change": pl.Float64,
        "amount_total_yuan": pl.Float64,
        "weighted_pct_change": pl.Float64,
    }
    if not snapshot.rows:
        return pl.DataFrame(schema=schema)
    records: list[dict[str, Any]] = []
    for row in snapshot.rows:
        records.append(
            {
                "quote_date": snapshot.quote_date,
                "source": snapshot.source,
                "status": snapshot.status,
                "mapped_count": snapshot.mapped_count,
                "industry_count": snapshot.industry_count,
                "industry": row.industry,
                "member_count": row.member_count,
                "priced_count": row.priced_count,
                "advance_count": row.advance_count,
                "decline_count": row.decline_count,
                "flat_count": row.flat_count,
                "advance_share": row.advance_share,
                "decline_share": row.decline_share,
                "advance_decline_ratio": row.advance_decline_ratio,
                "strong_up_count": row.strong_up_count,
                "strong_down_count": row.strong_down_count,
                "median_pct_change": row.median_pct_change,
                "amount_total_yuan": row.amount_total_yuan,
                "weighted_pct_change": row.weighted_pct_change,
            }
        )
    return pl.DataFrame(records)


__all__ = ["empty_industry_snapshot", "industry_snapshot_to_frame"]
