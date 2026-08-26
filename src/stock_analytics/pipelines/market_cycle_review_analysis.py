"""市场跨周期复盘的统计聚合逻辑。"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from itertools import pairwise
from typing import Any

DIMENSION_KEYS: tuple[str, ...] = (
    "valuation",
    "fund_flow",
    "sentiment",
    "technical",
    "fundamental",
    "macro_liquidity",
)
FACT_KEYS: tuple[str, ...] = (
    "main_money_net_inflow_share",
    "main_money_net_inflow_share_20d_cum",
    "margin_balance_growth_20d",
    "margin_balance_growth_60d",
    "market_amount_percentile_1250d",
    "turnover_rate_percentile_1250d",
    "advance_share",
    "above_ma20_share",
    "above_ma60_share",
    "return_20d",
    "amount_top_5pct_share",
)
EXTREME_KEYS: tuple[str, ...] = (
    "composite",
    "fund_flow",
    "sentiment",
    "technical",
    "valuation",
    "positive_return_20d_count",
    "positive_return_60d_count",
    "market_amount_percentile_1250d",
    "turnover_rate_percentile_1250d",
    "margin_balance_growth_20d",
    "above_ma20_share",
    "above_ma60_share",
)


def _build_payload(
    dates: list[str],
    market_rows: list[dict[str, Any]],
    panel_rows: list[dict[str, Any]],
    *,
    consistency_status: str = "not_checked",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": dates[0],
        "end_date": dates[-1],
        "date_count": len(dates),
        "consistency": {"status": consistency_status},
        "market_summary": _market_summary(market_rows),
        "phase_summary": _phase_summary(market_rows),
        "signal_days": _signal_days(market_rows),
        "industry_frequency": _industry_frequency(market_rows, panel_rows, dates),
        "quant_brief": {
            "available_date_count": sum(
                bool(row.get("quant_brief_available")) for row in market_rows
            ),
            "missing_dates": [
                row["date"] for row in market_rows if not row.get("quant_brief_available")
            ],
            "nature_counts": dict(
                Counter(row["quant_nature"] for row in market_rows if row.get("quant_nature"))
            ),
            "veto_status_counts": dict(
                Counter(
                    row["quant_veto_status"] for row in market_rows if row.get("quant_veto_status")
                )
            ),
            "priority_counts": _list_counter(market_rows, "quant_priority_industries"),
            "avoid_counts": _list_counter(market_rows, "quant_avoid_industries"),
        },
        "daily_rows": market_rows,
    }


def _market_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "composite",
        *DIMENSION_KEYS,
        "fast_temperature",
        "slow_temperature",
        "divergence",
        "positive_return_20d_count",
        "positive_return_60d_count",
    )
    summary = {key: _series_summary(rows, key) for key in keys}
    return {
        "series": summary,
        "risk_level_counts": dict(Counter(row["risk_level"] for row in rows)),
        "structure_health_counts": dict(Counter(row["structure_health"] for row in rows)),
        "divergence_level_counts": dict(
            Counter(row["divergence_level"] for row in rows if row.get("divergence_level"))
        ),
    }


def _series_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [(row["date"], _to_float(row.get(key))) for row in rows]
    finite = [(day, value) for day, value in values if math.isfinite(value)]
    if not finite:
        return {"status": "missing"}
    min_item = min(finite, key=lambda item: item[1])
    max_item = max(finite, key=lambda item: item[1])
    return {
        "start": round(finite[0][1], 4),
        "end": round(finite[-1][1], 4),
        "min": {"date": min_item[0], "value": round(min_item[1], 4)},
        "max": {"date": max_item[0], "value": round(max_item[1], 4)},
        "mean": round(sum(value for _, value in finite) / len(finite), 4),
    }


def _phase_summary(rows: list[dict[str, Any]], size: int = 10) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    for index in range(0, len(rows), size):
        chunk = rows[index : index + size]
        risk_counts = Counter(row.get("risk_level") or "低到中等" for row in chunk)
        primary_risk = risk_counts.most_common(1)[0][0] if risk_counts else "低到中等"
        if len(risk_counts) == 1:
            risk_desc = primary_risk
        else:
            elevated = [
                f"{count}天{level}"
                for level, count in risk_counts.most_common()
                if level != "低到中等"
            ]
            if elevated:
                risk_desc = f"{primary_risk} (含{'、'.join(elevated)})"
            else:
                risk_desc = _format_counts(dict(risk_counts))
        phases.append(
            {
                "start_date": chunk[0]["date"],
                "end_date": chunk[-1]["date"],
                "date_count": len(chunk),
                "composite": _mean(chunk, "composite"),
                "risk_level": risk_desc,
                "fund_flow": _mean(chunk, "fund_flow"),
                "technical": _mean(chunk, "technical"),
                "sentiment": _mean(chunk, "sentiment"),
                "positive_return_20d_count": _mean(chunk, "positive_return_20d_count"),
                "positive_return_60d_count": _mean(chunk, "positive_return_60d_count"),
            }
        )
    return phases


def _signal_days(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reasons: dict[str, list[str]] = defaultdict(list)
    _add_state_changes(rows, reasons)
    _add_extremes(rows, reasons)
    _add_threshold_crossings(rows, reasons)
    _add_daily_delta_extremes(rows, reasons)
    return [_signal_payload(row, reasons[row["date"]]) for row in rows if reasons.get(row["date"])]


def _add_state_changes(rows: list[dict[str, Any]], reasons: dict[str, list[str]]) -> None:
    previous: dict[str, Any] | None = None
    for row in rows:
        if previous is None:
            reasons[row["date"]].append("区间起点")
        elif row["risk_level"] != previous["risk_level"]:
            reasons[row["date"]].append(f"系统风险切换为 {row['risk_level']}")
        elif row["structure_health"] != previous["structure_health"]:
            reasons[row["date"]].append(f"结构健康度切换为 {row['structure_health']}")
        previous = row


METRIC_KEY_NAMES: dict[str, str] = {
    "composite": "综合温度",
    "valuation": "估值面",
    "fund_flow": "资金面",
    "sentiment": "情绪面",
    "technical": "技术面",
    "fundamental": "基本面",
    "macro_liquidity": "宏观流动性",
    "positive_return_20d_count": "20日上涨行业数",
    "positive_return_60d_count": "60日上涨行业数",
    "market_amount_percentile_1250d": "自由流通换手率五年分位",
    "turnover_rate_percentile_1250d": "换手率五年分位",
    "margin_balance_growth_20d": "两融余额20日变化",
    "above_ma20_share": "站上20日线占比",
    "above_ma60_share": "站上60日线占比",
    "return_20d": "20日收益率",
    "advance_share": "上涨家数占比",
    "main_money_net_inflow_share": "主力净流入占比",
    "main_money_net_inflow_share_20d_cum": "主力净流入20日累计占比",
    "margin_balance_growth_60d": "两融余额60日变化",
}


def _format_signal_value(key: str, value: float) -> str:
    if not math.isfinite(value):
        return ""
    if key in {
        "margin_balance_growth_20d",
        "above_ma20_share",
        "above_ma60_share",
        "advance_share",
        "main_money_net_inflow_share",
        "main_money_net_inflow_share_20d_cum",
        "margin_balance_growth_60d",
        "return_20d",
    }:
        if key in {"margin_balance_growth_20d", "return_20d", "main_money_net_inflow_share"}:
            return f"{value * 100:+.2f}%"
        return f"{value * 100:.2f}%"
    if key in {"positive_return_20d_count", "positive_return_60d_count"}:
        return f"{round(value)}"
    return f"{value:.2f}"


def _add_extremes(rows: list[dict[str, Any]], reasons: dict[str, list[str]]) -> None:
    for key in EXTREME_KEYS:
        finite = [(row["date"], _to_float(row.get(key))) for row in rows]
        finite = [(day, value) for day, value in finite if math.isfinite(value)]
        if not finite:
            continue
        min_day, min_value = min(finite, key=lambda item: item[1])
        max_day, max_value = max(finite, key=lambda item: item[1])
        label = METRIC_KEY_NAMES.get(key, key)
        min_text = _format_signal_value(key, min_value)
        max_text = _format_signal_value(key, max_value)
        reasons[min_day].append(f"{label} 区间最低 {min_text}")
        reasons[max_day].append(f"{label} 区间最高 {max_text}")


def _add_threshold_crossings(rows: list[dict[str, Any]], reasons: dict[str, list[str]]) -> None:
    thresholds = (
        ("composite", 60.0),
        ("fund_flow", 50.0),
        ("technical", 40.0),
        ("technical", 60.0),
        ("positive_return_20d_count", 10.0),
        ("positive_return_20d_count", 20.0),
        ("positive_return_60d_count", 3.0),
    )
    for previous, current in pairwise(rows):
        for key, threshold in thresholds:
            before = _to_float(previous.get(key))
            after = _to_float(current.get(key))
            label = METRIC_KEY_NAMES.get(key, key)
            thresh_text = _format_signal_value(key, threshold)
            if before < threshold <= after:
                reasons[current["date"]].append(f"{label} 上穿 {thresh_text}")
            elif before >= threshold > after:
                reasons[current["date"]].append(f"{label} 下穿 {thresh_text}")


def _add_daily_delta_extremes(rows: list[dict[str, Any]], reasons: dict[str, list[str]]) -> None:
    keys = ("composite", "fund_flow", "technical", "sentiment")
    for key in keys:
        deltas = []
        for previous, current in pairwise(rows):
            delta = _to_float(current.get(key)) - _to_float(previous.get(key))
            if math.isfinite(delta):
                deltas.append((current["date"], delta))
        if not deltas:
            continue
        up_day, up_delta = max(deltas, key=lambda item: item[1])
        down_day, down_delta = min(deltas, key=lambda item: item[1])
        label = METRIC_KEY_NAMES.get(key, key)
        reasons[up_day].append(f"{label} 单日最大上行 {up_delta:+.2f}")
        reasons[down_day].append(f"{label} 单日最大下行 {down_delta:+.2f}")


def _signal_payload(row: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    keys = (
        "date",
        "composite",
        "risk_level",
        "fund_flow",
        "technical",
        "sentiment",
        "valuation",
        "fast_temperature",
        "slow_temperature",
        "divergence",
        "divergence_level",
        "structure_health",
        "positive_return_20d_count",
        "positive_return_60d_count",
        "quant_nature",
        "quant_veto_status",
        "quant_top5pct_share",
    )
    payload = {key: row.get(key) for key in keys}
    payload["reasons"] = reasons
    return payload


def _industry_frequency(
    market_rows: list[dict[str, Any]],
    panel_rows: list[dict[str, Any]],
    dates: list[str],
) -> dict[str, Any]:
    return {
        "brief_candidate_counts": _list_counter(market_rows, "candidate_industries"),
        "brief_risk_counts": _list_counter(market_rows, "risk_industries"),
        "brief_lagging_counts": _list_counter(market_rows, "lagging_industries"),
        "quant_priority_counts": _list_counter(market_rows, "quant_priority_industries"),
        "quant_avoid_counts": _list_counter(market_rows, "quant_avoid_industries"),
        "top5_counts": _panel_counter(
            panel_rows,
            "structure_rank",
            lambda value: _to_float(value) <= 5,
        ),
        "top1_counts": _panel_counter(
            panel_rows,
            "structure_rank",
            lambda value: _to_float(value) == 1,
        ),
        "crowding_counts": _panel_counter(
            panel_rows,
            "crowding_temperature",
            lambda value: _to_float(value) >= 80,
        ),
        "tcr_change": _tcr_change(panel_rows, dates),
    }


def _list_counter(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(row.get(key) or [])
    return [{"industry_name": name, "days": days} for name, days in counter.most_common()]


def _panel_counter(
    rows: list[dict[str, Any]],
    key: str,
    predicate: Any,
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        if predicate(row.get(key)):
            counter[str(row.get("industry_name"))] += 1
    return [{"industry_name": name, "days": days} for name, days in counter.most_common()]


def _tcr_change(rows: list[dict[str, Any]], dates: list[str]) -> list[dict[str, Any]]:
    size = max(1, len(dates) // 3)
    early_dates = set(dates[:size])
    late_dates = set(dates[-size:])
    early = _avg_by_industry(rows, early_dates, "tcr")
    late = _avg_by_industry(rows, late_dates, "tcr")
    changes = []
    for name in sorted(set(early) & set(late)):
        changes.append(
            {
                "industry_name": name,
                "early_tcr": round(early[name], 4),
                "late_tcr": round(late[name], 4),
                "delta": round(late[name] - early[name], 4),
            }
        )
    return sorted(changes, key=lambda row: row["delta"], reverse=True)


def _avg_by_industry(
    rows: list[dict[str, Any]],
    selected_dates: set[str],
    key: str,
) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = _to_float(row.get(key))
        if row.get("date") in selected_dates and math.isfinite(value):
            values[str(row.get("industry_name"))].append(value)
    return {name: sum(items) / len(items) for name, items in values.items() if items}


def _format_counts(counts: dict[str, int]) -> str:
    return "，".join(f"{key} {value}天" for key, value in counts.items())


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_to_float(row.get(key)) for row in rows]
    finite = [value for value in values if math.isfinite(value)]
    return round(sum(finite) / len(finite), 4) if finite else None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
