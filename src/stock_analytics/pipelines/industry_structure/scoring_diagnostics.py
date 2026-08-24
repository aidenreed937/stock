"""行业结构评分摘要与诊断。"""

from __future__ import annotations

from typing import Any

from stock_analytics.pipelines.industry_structure.scoring_utils import (
    _as_float,
    _median_number,
    _round_or_none,
)


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


def _count_by_text(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        text = str(value)
        counts[text] = counts.get(text, 0) + 1
    return counts


def _trend_diagnostics(rows: list[dict[str, Any]], top_limit: int = 10) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    if not ok_rows:
        return {
            "status": "insufficient",
            "message": "行业结构趋势诊断样本不足。",
            "top_limit": top_limit,
        }
    top_rows = sorted(
        ok_rows,
        key=lambda item: _as_float(item.get("structure_score")) or -1.0,
        reverse=True,
    )[:top_limit]
    top_negative_60d = []
    for row in top_rows:
        return_60d = _as_float(row.get("return_60d"))
        if return_60d is not None and return_60d < 0:
            top_negative_60d.append(row)
    median_20d = _median_number(row.get("return_20d") for row in ok_rows)
    median_60d = _median_number(row.get("return_60d") for row in ok_rows)
    positive_20d_count = sum(
        1
        for row in ok_rows
        if (value := _as_float(row.get("return_20d"))) is not None and value > 0
    )
    positive_60d_count = sum(
        1
        for row in ok_rows
        if (value := _as_float(row.get("return_60d"))) is not None and value > 0
    )
    positive_20d_share = positive_20d_count / len(ok_rows) if ok_rows else 0.0
    top_negative_60d_share = len(top_negative_60d) / len(top_rows) if top_rows else 0.0
    if top_rows and top_negative_60d_share >= 0.6 and positive_20d_share >= 0.6:
        status = "short_rebound_medium_unconfirmed"
        message = "结构领先行业多数60日收益仍为负，当前更像短期修复，中期趋势尚未全面确认。"
    elif top_rows and top_negative_60d_share >= 0.6:
        status = "localized_strength_weak_breadth"
        message = (
            "结构领先行业多数60日收益仍为负，且20日上涨行业扩散不足，"
            "当前更像局部强势、整体偏弱，中期趋势尚未全面确认。"
        )
    elif median_20d is not None and median_60d is not None and median_20d > 0 > median_60d:
        status = "short_rebound_medium_unconfirmed"
        message = "行业20日中位收益转正但60日中位收益仍为负，短线强于中期。"
    elif median_20d is not None and median_60d is not None and median_20d > 0 and median_60d > 0:
        status = "trend_confirming"
        message = "20日和60日行业中位收益同向偏强，中期趋势确认度较高。"
    else:
        status = "neutral"
        message = "行业中短期趋势没有明显同向确认信号。"
    return {
        "status": status,
        "message": message,
        "top_limit": top_limit,
        "top_negative_60d_count": len(top_negative_60d),
        "top_count": len(top_rows),
        "median_return_20d": _round_or_none(median_20d),
        "median_return_60d": _round_or_none(median_60d),
        "positive_return_20d_count": positive_20d_count,
        "positive_return_60d_count": positive_60d_count,
        "scored_industry_count": len(ok_rows),
    }


def _structure_health(rows: list[dict[str, Any]], top_limit: int = 10) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    if not ok_rows:
        return {
            "status": "insufficient",
            "level": "不可判定",
            "message": "行业结构健康度样本不足。",
            "scored_industry_count": 0,
        }
    top_rows = sorted(
        ok_rows,
        key=lambda item: _as_float(item.get("structure_score")) or -1.0,
        reverse=True,
    )[:top_limit]
    scored_count = len(ok_rows)
    positive_20d_count = sum(
        1
        for row in ok_rows
        if (value := _as_float(row.get("return_20d"))) is not None and value > 0
    )
    positive_60d_count = sum(
        1
        for row in ok_rows
        if (value := _as_float(row.get("return_60d"))) is not None and value > 0
    )
    crowded_count = sum(
        1
        for row in ok_rows
        if (value := _as_float(row.get("crowding_temperature"))) is not None and value >= 80
    )
    strong_count = sum(1 for row in ok_rows if "强势主线" in str(row.get("tags", "")))
    top_negative_60d_count = sum(
        1
        for row in top_rows
        if (value := _as_float(row.get("return_60d"))) is not None and value < 0
    )
    breadth_20d = positive_20d_count / scored_count * 100.0
    breadth_60d = positive_60d_count / scored_count * 100.0
    crowded_share = crowded_count / scored_count * 100.0
    top_negative_share = top_negative_60d_count / len(top_rows) * 100.0 if top_rows else 0.0

    if breadth_20d >= 60 and breadth_60d < 35 and top_negative_share >= 60:
        status = "short_rebound_medium_unconfirmed"
        level = "修复中但偏脆弱"
        message = "短线行业扩散较强，但60日趋势和领先行业中期确认不足，结构健康度尚未确认。"
    elif crowded_share >= 30 and breadth_60d < 50:
        status = "crowded_and_unconfirmed"
        level = "偏脆弱"
        message = "拥挤行业占比较高且中期扩散不足，结构风险高于结构机会。"
    elif breadth_20d >= 60 and breadth_60d >= 50 and crowded_share < 25:
        status = "healthy_confirming"
        level = "健康"
        message = "20日和60日行业扩散同步改善，且拥挤行业占比不高，结构较健康。"
    elif breadth_20d >= 50:
        status = "mixed_repair"
        level = "中性修复"
        message = "短线扩散尚可，但中期趋势、拥挤度或主线强度仍有分化。"
    else:
        status = "weak_structure"
        level = "偏弱"
        message = "上涨行业扩散不足，结构健康度偏弱。"

    return {
        "status": status,
        "level": level,
        "message": message,
        "scored_industry_count": scored_count,
        "positive_return_20d_count": positive_20d_count,
        "positive_return_20d_share": _round_or_none(breadth_20d),
        "positive_return_60d_count": positive_60d_count,
        "positive_return_60d_share": _round_or_none(breadth_60d),
        "top_limit": top_limit,
        "top_negative_60d_count": top_negative_60d_count,
        "top_negative_60d_share": _round_or_none(top_negative_share),
        "crowded_industry_count": crowded_count,
        "crowded_industry_share": _round_or_none(crowded_share),
        "strong_trend_count": strong_count,
    }
