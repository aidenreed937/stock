"""行业结构评分数学工具。"""

from __future__ import annotations

from datetime import date
from math import isfinite
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.primitives.rules import percentile_rank

if TYPE_CHECKING:
    from collections.abc import Iterable


def _apply_cross_percentile(
    rows: list[dict[str, Any]],
    source: str,
    target: str,
    *,
    inverse: bool = False,
) -> None:
    values = [
        (index, value)
        for index, row in enumerate(rows)
        if (value := _as_float(row.get(source))) is not None
    ]
    if len(values) < 2:
        return
    value_series = pl.Series([value for _, value in values])
    for index, value in values:
        percentile = percentile_rank(value_series, len(values), current=value)
        rows[index][target] = (
            round(100.0 - percentile if inverse else percentile, 2)
            if percentile is not None
            else None
        )


def _apply_fund_flow_percentiles(rows: list[dict[str, Any]]) -> None:
    _apply_cross_percentile(rows, "money_net_inflow_share_20d", "_money_inflow_pct")
    _apply_cross_percentile(
        rows,
        "large_money_net_inflow_share_20d",
        "_large_money_inflow_pct",
    )
    _apply_cross_percentile(rows, "money_net_inflow_share_5d", "_short_money_inflow_pct")


def _top_rows(rows: list[dict[str, Any]], key: str, limit: int = 5) -> list[dict[str, Any]]:
    valid = [row for row in rows if _as_float(row.get(key)) is not None]
    valid.sort(key=lambda row: _as_float(row.get(key)) or -1.0, reverse=True)
    return [_summary_row(row, key) for row in valid[:limit]]


def _bottom_rows(rows: list[dict[str, Any]], key: str, limit: int = 5) -> list[dict[str, Any]]:
    valid = [row for row in rows if _as_float(row.get(key)) is not None]
    valid.sort(key=lambda row: _as_float(row.get(key)) or 101.0)
    return [_summary_row(row, key) for row in valid[:limit]]


def _tagged_rows(rows: list[dict[str, Any]], tag: str, limit: int = 8) -> list[dict[str, Any]]:
    tagged = [row for row in rows if tag in str(row.get("tags", ""))]
    tagged.sort(key=lambda row: _as_float(row.get("structure_score")) or -1.0, reverse=True)
    return [_summary_row(row, "structure_score") for row in tagged[:limit]]


def _summary_row(row: dict[str, Any], score_key: str) -> dict[str, Any]:
    return {
        "industry_code": row.get("industry_code"),
        "industry_name": row.get("industry_name"),
        "score": _round_or_none(row.get(score_key)),
        "structure_score": _round_or_none(row.get("structure_score")),
        "return_20d": _round_or_none(row.get("return_20d")),
        "return_60d": _round_or_none(row.get("return_60d")),
        "tcr": _round_or_none(row.get("tcr")),
        "fund_flow_score": _round_or_none(row.get("fund_flow_score")),
        "money_net_inflow_share_20d": _round_or_none(row.get("money_net_inflow_share_20d")),
        "large_money_net_inflow_share_20d": _round_or_none(
            row.get("large_money_net_inflow_share_20d")
        ),
        "fundamental_status": row.get("fundamental_status"),
        "tags": row.get("tags", ""),
    }


def _mean_available(*values: object) -> float | None:
    clean: list[float] = []
    for value in values:
        numeric = _as_float(value)
        if numeric is not None:
            clean.append(numeric)
    if not clean:
        return None
    return round(sum(clean) / len(clean), 2)


def _median_number(values: Iterable[object]) -> float | None:
    clean = sorted(numeric for value in values if (numeric := _as_float(value)) is not None)
    if not clean:
        return None
    middle = len(clean) // 2
    if len(clean) % 2 == 1:
        return clean[middle]
    return (clean[middle - 1] + clean[middle]) / 2.0


def _parse_date_value(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace("-", "")[:8]
    if len(compact) == 8 and compact.isdigit():
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    return None


def _inverse(value: object) -> float | None:
    numeric = _as_float(value)
    if numeric is None:
        return None
    return _clip(100.0 - numeric)


def _clip(value: object) -> float | None:
    numeric = _as_float(value)
    if numeric is None:
        return None
    return round(min(100.0, max(0.0, numeric)), 2)


def _round_or_none(value: object) -> float | None:
    numeric = _as_float(value)
    return None if numeric is None else round(numeric, 2)


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
