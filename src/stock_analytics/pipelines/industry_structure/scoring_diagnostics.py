"""行业结构评分摘要、诊断与口径方法论。"""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from stock_core.config.analytics_industry_structure import IndustryStructureConfig


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
    top_negative_60d = [
        row for row in top_rows if (val := _as_float(row.get("return_60d"))) is not None and val < 0
    ]
    median_20d = _median_number(row.get("return_20d") for row in ok_rows)
    median_60d = _median_number(row.get("return_60d") for row in ok_rows)
    positive_20d_count = sum(
        1 for row in ok_rows if (val := _as_float(row.get("return_20d"))) is not None and val > 0
    )
    positive_60d_count = sum(
        1 for row in ok_rows if (val := _as_float(row.get("return_60d"))) is not None and val > 0
    )
    positive_20d_share = positive_20d_count / len(ok_rows) if ok_rows else 0.0
    top_negative_60d_share = len(top_negative_60d) / len(top_rows) if top_rows else 0.0

    if top_rows and top_negative_60d_share >= 0.6 and positive_20d_share >= 0.6:
        status = "short_rebound_medium_unconfirmed"
        message = "结构领先行业多数60日收益仍为负，当前更像短期修复，中期趋势尚未全面确认。"
    elif top_rows and top_negative_60d_share >= 0.6:
        status = "localized_strength_weak_breadth"
        message = "结构领先行业多数60日收益仍为负，且20日上涨行业扩散不足，当前更像局部强势、整体偏弱，中期趋势尚未全面确认。"
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
    pos_20d_count = sum(
        1 for row in ok_rows if (val := _as_float(row.get("return_20d"))) is not None and val > 0
    )
    pos_60d_count = sum(
        1 for row in ok_rows if (val := _as_float(row.get("return_60d"))) is not None and val > 0
    )
    crowded_count = sum(
        1
        for row in ok_rows
        if (val := _as_float(row.get("crowding_temperature"))) is not None and val >= 80
    )
    strong_count = sum(1 for row in ok_rows if "强势主线" in str(row.get("tags", "")))
    top_neg_60d_count = sum(
        1 for row in top_rows if (val := _as_float(row.get("return_60d"))) is not None and val < 0
    )

    b_20d = pos_20d_count / scored_count * 100.0
    b_60d = pos_60d_count / scored_count * 100.0
    crowded_share = crowded_count / scored_count * 100.0
    top_neg_share = top_neg_60d_count / len(top_rows) * 100.0 if top_rows else 0.0

    if b_20d >= 60 and b_60d < 35 and top_neg_share >= 60:
        status, level, msg = (
            "short_rebound_medium_unconfirmed",
            "修复中但偏脆弱",
            "短线行业扩散较强，但60日趋势和领先行业中期确认不足，结构健康度尚未确认。",
        )
    elif crowded_share >= 30 and b_60d < 50:
        status, level, msg = (
            "crowded_and_unconfirmed",
            "偏脆弱",
            "拥挤行业占比较高且中期扩散不足，结构风险高于结构机会。",
        )
    elif b_20d >= 60 and b_60d >= 50 and crowded_share < 25:
        status, level, msg = (
            "healthy_confirming",
            "健康",
            "20日和60日行业扩散同步改善，且拥挤行业占比不高，结构较健康。",
        )
    elif b_20d >= 50:
        status, level, msg = (
            "mixed_repair",
            "中性修复",
            "短线扩散尚可，但中期趋势、拥挤度或主线强度仍有分化。",
        )
    else:
        status, level, msg = "weak_structure", "偏弱", "上涨行业扩散不足，结构健康度偏弱。"

    return {
        "status": status,
        "level": level,
        "message": msg,
        "scored_industry_count": scored_count,
        "positive_return_20d_count": pos_20d_count,
        "positive_return_20d_share": _round_or_none(b_20d),
        "positive_return_60d_count": pos_60d_count,
        "positive_return_60d_share": _round_or_none(b_60d),
        "top_limit": top_limit,
        "top_negative_60d_count": top_neg_60d_count,
        "top_negative_60d_share": _round_or_none(top_neg_share),
        "crowded_industry_count": crowded_count,
        "crowded_industry_share": _round_or_none(crowded_share),
        "strong_trend_count": strong_count,
    }


def _methodology(config: IndustryStructureConfig) -> dict[str, Any]:
    fb = config.fundamental_blend
    return {
        "score_type": "行业结构分是申万一级行业横截面排序分，不并入六维市场温度。",
        "missing_policy": "缺失子项不填补，对可用子项按有效权重重归一。",
        "field_definitions": {
            "tcr": f"TCR=最近{config.main_window}个行业交易日行业成交额占全部申万一级成交额比例均值(%)。",
            "tcr_percentile": "该行业自身历史 TCR 分位，越高代表成交越集中。",
            "crowding_temperature": "等于 TCR 历史分位，越高越拥挤。",
            "crowding_score": "100-crowding_temperature，越高代表越不拥挤。",
            "fund_flow_score": "行业20日主力、大单、5日主力净流入占比横截面分位等权合成（观察项）。",
        },
        "subscores": {
            "momentum_score": {
                "components": [
                    "return_20d 分位",
                    "relative_return_20d 分位",
                    "return_60d 分位",
                    "ma_bias_20d 分位",
                ],
                "direction": "越强越高",
                "normalization": "基准日申万一级行业横截面分位 (0-100)。",
            },
            "valuation_score": {
                "components": [
                    "100-PE五年历史分位",
                    "100-PB五年历史分位",
                    "PB-ROE残差横截面反向分位",
                ],
                "direction": "越便宜、PB-ROE越低估越高",
                "normalization": "历史分位与横截面反向分位混合 (0-100)。",
            },
            "fundamental_score": {
                "components": ["official_fundamental_score", "fast_fundamental_score"],
                "direction": "越强越高",
                "normalization": "正式财报使用历史分位；快速项使用当前横截面分位。",
                "cadence": "正式财报是季频底座；预告、快报和研报用于中报窗口过渡确认。",
                "blend": f"超过 {fb.stale_after_days} 天视为滞后；fresh 权 {fb.official_weight:.0%}/{fb.fast_weight:.0%}，stale 权 {fb.stale_official_weight:.0%}/{fb.stale_fast_weight:.0%}。",
            },
            "crowding_score": {
                "components": ["100-TCR历史分位"],
                "direction": "越不拥挤越高",
                "normalization": "行业自身历史反向分位 (0-100)。",
            },
            "fund_flow_score": {
                "components": [
                    "20D主力净流入占比分位",
                    "20D大单净流入占比分位",
                    "5D主力净流入占比分位",
                ],
                "direction": "越流入越高",
                "normalization": "横截面分位 (0-100)；观察项不入结构总分。",
            },
        },
        "tag_rules": {
            "强势主线": "momentum_score>=75 且 return_20d>0。",
            "低估改善": "valuation_score>=70 且 fundamental_score>=55。",
            "拥挤风险": "crowding_temperature>=80。",
            "超跌修复": "return_20d<0 且 return_5d>0。",
            "景气承压": "fundamental_score<40。",
            "相对占优": "relative_return_20d>0。",
            "资金确认": "fund_flow_score>=70 且 money_net_inflow_share_20d>0。",
            "资金流出压力": "fund_flow_score<=30 且 money_net_inflow_share_20d<0。",
            "中性观察": "不满足以上标签时使用。",
        },
        "group_rules": {
            "结构分Top": "structure_score 降序前10。",
            "动量主线": "momentum_score 降序前5。",
            "低估线索": "valuation_score 降序前5。",
            "强势主线": "带有强势主线标签，按 structure_score 降序。",
            "低估改善": "带有低估改善标签，按 structure_score 降序。",
            "拥挤风险": "带有拥挤风险标签，按 structure_score 降序。",
            "资金确认": "带有资金确认标签，按 structure_score 降序。",
            "资金流出压力": "带有资金流出压力标签，按 structure_score 降序。",
            "落后方向": "structure_score 升序后5。",
        },
        "data_mapping": "行业代码优先由 tushare.index_classify 识别申万2021一级行业。",
    }


def _median_number(values: Iterable[object]) -> float | None:
    clean = sorted(num for v in values if (num := _as_float(v)) is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    return clean[mid] if len(clean) % 2 == 1 else (clean[mid - 1] + clean[mid]) / 2.0


def _round_or_none(value: object) -> float | None:
    num = _as_float(value)
    return None if num is None else round(num, 2)


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        num = float(value)
        return num if isfinite(num) else None
    except (TypeError, ValueError):
        return None
