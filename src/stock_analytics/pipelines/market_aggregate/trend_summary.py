"""全市场聚合短期趋势摘要计算。"""

from __future__ import annotations

import math
from typing import Any


def build_trend_summary(
    history_rows: list[dict[str, Any]],
    current_row: dict[str, Any],
) -> dict[str, Any]:
    """计算当前盘中快照相对前置日均值的结构性变化。"""
    previous = history_rows[-1]
    breadth_change_pp = _delta_from_average(current_row, history_rows, "advance_share", scale=100)
    decline_change_pp = _delta_from_average(current_row, history_rows, "decline_share", scale=100)
    strong_up_change_pp = _delta_from_average(
        current_row, history_rows, "strong_up_share", scale=100
    )
    strong_down_change_pp = _delta_from_average(
        current_row,
        history_rows,
        "strong_down_share",
        scale=100,
    )
    weighted_change_pp = _delta_from_average(
        current_row,
        history_rows,
        "weighted_pct_change",
        scale=1,
    )
    if (
        breadth_change_pp is not None
        and breadth_change_pp > 0
        and weighted_change_pp is not None
        and weighted_change_pp >= 0
    ):
        direction = "improving"
    elif (
        breadth_change_pp is not None
        and breadth_change_pp < 0
        and weighted_change_pp is not None
        and weighted_change_pp <= 0
    ):
        direction = "weakening"
    else:
        direction = "range_bound"
    return {
        "direction": direction,
        "history_average": {
            "advance_share": _average(history_rows, "advance_share"),
            "decline_share": _average(history_rows, "decline_share"),
            "strong_up_share": _average(history_rows, "strong_up_share"),
            "strong_down_share": _average(history_rows, "strong_down_share"),
            "weighted_pct_change": _average(history_rows, "weighted_pct_change"),
            "median_pct_change": _average(history_rows, "median_pct_change"),
            "amount_top_5pct_share": _average(history_rows, "amount_top_5pct_share"),
            "amount_total_yuan": _average(history_rows, "amount_total_yuan"),
            "free_float_turnover_pct": _average(history_rows, "free_float_turnover_pct"),
        },
        "current_vs_history_average": {
            "advance_share_change_pp": breadth_change_pp,
            "decline_share_change_pp": decline_change_pp,
            "strong_up_share_change_pp": strong_up_change_pp,
            "strong_down_share_change_pp": strong_down_change_pp,
            "weighted_pct_change_change_pp": weighted_change_pp,
            "median_pct_change_change_pp": _delta_from_average(
                current_row,
                history_rows,
                "median_pct_change",
                scale=1,
            ),
            "amount_top_5pct_share_change_pp": _delta_from_average(
                current_row,
                history_rows,
                "amount_top_5pct_share",
                scale=100,
            ),
            "amount_comparison": "not_comparable_intraday_vs_full_day",
            "free_float_turnover_comparison": "not_comparable_intraday_vs_full_day",
        },
        "previous_date": previous["date"],
        "latest_vs_previous": {
            "advance_share_change_pp": _delta(current_row, previous, "advance_share", scale=100),
            "weighted_pct_change_change_pp": _delta(
                current_row,
                previous,
                "weighted_pct_change",
                scale=1,
            ),
            "decline_share_change_pp": _delta(current_row, previous, "decline_share", scale=100),
            "amount_top_5pct_share_change_pp": _delta(
                current_row,
                previous,
                "amount_top_5pct_share",
                scale=100,
            ),
        },
    }


def _average(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [_as_float(row.get(field)) for row in rows]
    valid = [value for value in values if value is not None]
    return sum(valid) / len(valid) if valid else None


def _delta_from_average(
    current: dict[str, Any],
    history: list[dict[str, Any]],
    field: str,
    *,
    scale: float,
) -> float | None:
    average = _average(history, field)
    current_value = _as_float(current.get(field))
    if average is None or current_value is None:
        return None
    return (current_value - average) * scale


def _delta(
    current: dict[str, Any],
    reference: dict[str, Any],
    field: str,
    *,
    scale: float,
) -> float | None:
    current_value = _as_float(current.get(field))
    reference_value = _as_float(reference.get(field))
    if current_value is None or reference_value is None:
        return None
    return (current_value - reference_value) * scale


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
