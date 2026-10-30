"""期货龙虎榜 RAW/Curated 转换。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_data.fetcher.industry.chemicals.schemas import (
    HOLD_RANK_RAW_SCHEMA,
    HOLD_RANK_SCHEMA,
)


def build_hold_rank_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    """校正并返回席位榜 RAW 表。"""
    return df if not df.is_empty() else pl.DataFrame(schema=HOLD_RANK_RAW_SCHEMA)


def build_hold_rank_curated_frame(df: pl.DataFrame) -> pl.DataFrame:
    """从席位榜 RAW 行计算前 20、集中度和多空状态。"""
    if df.is_empty():
        return pl.DataFrame(schema=HOLD_RANK_SCHEMA)

    records: list[dict[str, Any]] = []
    for keys, group in df.group_by(
        ["trade_date", "symbol", "name", "contract"], maintain_order=True
    ):
        trade_date, symbol, name, contract = keys
        long_rows = _position_rows(group, "long")
        short_rows = _position_rows(group, "short")
        if not long_rows or not short_rows:
            continue

        long_rows.sort(
            key=lambda row: _required_float(row["position_volume_raw"]) or 0.0, reverse=True
        )
        short_rows.sort(
            key=lambda row: _required_float(row["position_volume_raw"]) or 0.0, reverse=True
        )
        long_vols = [_required_float(row["position_volume_raw"]) or 0.0 for row in long_rows]
        short_vols = [_required_float(row["position_volume_raw"]) or 0.0 for row in short_rows]
        top20_long = sum(long_vols)
        top20_short = sum(short_vols)
        net_long = top20_long - top20_short
        records.append(
            {
                "trade_date": trade_date,
                "symbol": symbol,
                "name": name,
                "contract": contract,
                "top20_long_vol": top20_long,
                "top20_short_vol": top20_short,
                "top20_net_long_vol": net_long,
                "top5_long_share_pct": round(sum(long_vols[:5]) / top20_long * 100.0, 2),
                "top5_short_share_pct": round(sum(short_vols[:5]) / top20_short * 100.0, 2),
                "top1_long_member": long_rows[0]["member_name_raw"],
                "top1_long_vol": long_vols[0],
                "top1_short_member": short_rows[0]["member_name_raw"],
                "top1_short_vol": short_vols[0],
                "smart_money_bias": (
                    "bullish" if net_long > 5000 else "bearish" if net_long < -5000 else "neutral"
                ),
                "source": "Sina_Exchange_Hold_Rank",
                "release_date": trade_date,
                "collected_at": group["collected_at"].drop_nulls().max(),
                "raw_content_sha256": group["raw_content_sha256"].drop_nulls().first() or "",
                "raw_snapshot_path": group["raw_snapshot_path"].drop_nulls().first() or "",
            }
        )
    if not records:
        return pl.DataFrame(schema=HOLD_RANK_SCHEMA)
    return pl.DataFrame(records, schema=HOLD_RANK_SCHEMA).sort(["symbol", "trade_date"])


def _position_rows(group: pl.DataFrame, side: str) -> list[dict[str, Any]]:
    return [
        row
        for row in group.filter(pl.col("side") == side).to_dicts()
        if _required_float(row.get("position_volume_raw")) is not None
    ]


def _required_float(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


__all__ = ["build_hold_rank_curated_frame", "build_hold_rank_raw_frame"]
