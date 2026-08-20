"""量化投研简报的结构化数据辅助函数。"""

from __future__ import annotations

from math import isfinite
from typing import Any

import polars as pl

from stock_reporting.interpretation.quant_brief.config import (
    QuantBriefConfig,
    TemperatureBandConfig,
)


def _temperature_band(
    config: QuantBriefConfig,
    value: float,
) -> TemperatureBandConfig:
    for band in config.temperature_bands:
        if band.upper_bound is None or value < band.upper_bound:
            return band
    return config.temperature_bands[-1]


def _breadth(industry_scores: dict[str, Any]) -> dict[str, int | float | None]:
    trend = _mapping(industry_scores.get("trend_diagnostics"))
    health = _mapping(industry_scores.get("structure_health"))

    def pick(key: str) -> float | None:
        value = _as_float(trend.get(key))
        return value if value is not None else _as_float(health.get(key))

    total = pick("scored_industry_count")
    count20 = pick("positive_return_20d_count")
    count60 = pick("positive_return_60d_count")
    share20 = pick("positive_return_20d_share")
    share60 = pick("positive_return_60d_share")
    if share20 is None and count20 is not None and total:
        share20 = count20 / total * 100
    if share60 is None and count60 is not None and total:
        share60 = count60 / total * 100
    return {
        "positive_20d_count": int(count20) if count20 is not None else None,
        "positive_60d_count": int(count60) if count60 is not None else None,
        "positive_20d_share": share20,
        "positive_60d_share": share60,
        "scored_industry_count": int(total) if total is not None else None,
    }


def _composite_delta(scores: dict[str, Any]) -> tuple[float | None, str]:
    drivers = _mapping(scores.get("drivers"))
    if drivers.get("status") != "ok":
        return None, "insufficient_comparison"
    value = _as_float(drivers.get("composite_delta"))
    return (value, "available") if value is not None else (None, "insufficient_comparison")


def _comparison_as_of(scores: dict[str, Any]) -> str | None:
    drivers = _mapping(scores.get("drivers"))
    value = drivers.get("comparison_as_of")
    return str(value) if value else None


def _fact_observation(facts: pl.DataFrame | None, metric_id: str) -> dict[str, Any]:
    if facts is None or facts.is_empty() or not {"metric_id", "category"}.issubset(facts.columns):
        return {}
    frame = facts.filter(
        (pl.col("category") == "metric_value") & (pl.col("metric_id") == metric_id)
    )
    if frame.is_empty():
        return {}
    rows = frame.to_dicts()
    rows.sort(key=lambda row: str(row.get("metric_date") or row.get("as_of_date") or ""))
    return rows[-1]


def _margin_observation(facts: pl.DataFrame | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for metric_id in (
        "margin_balance_growth_20d",
        "margin_balance_growth_60d",
        "margin_penetration",
        "margin_buy_share",
    ):
        row = _fact_observation(facts, metric_id)
        result[metric_id] = _as_float(row.get("value_float")) if row else None
        if row and row.get("metric_date") is not None:
            result[f"{metric_id}_date"] = _date_text(row.get("metric_date"))
    return result


def _funding_observation(facts: pl.DataFrame | None) -> dict[str, Any]:
    """读取主力资金、成交放量和两融健康度观察事实。"""
    metric_ids = (
        "main_large_order_net_inflow_share",
        "main_money_net_inflow_share",
        "main_money_net_inflow_share_20d_cum",
        "main_money_net_inflow_share_zscore_60d",
        "super_large_net_inflow_share",
        "market_amount_percentile_1250d",
        "margin_buy_share",
        "margin_balance_growth_20d",
        "margin_balance_growth_60d",
        "margin_penetration",
        "margin_penetration_percentile_1250d",
    )
    result: dict[str, Any] = {}
    for metric_id in metric_ids:
        row = _fact_observation(facts, metric_id)
        result[metric_id] = _as_float(row.get("value_float")) if row else None
        if row and row.get("metric_date") is not None:
            result[f"{metric_id}_date"] = _date_text(row.get("metric_date"))
    if result.get("main_large_order_net_inflow_share") is None:
        result["main_large_order_net_inflow_share"] = result.get("main_money_net_inflow_share")
        result["main_large_order_net_inflow_share_source"] = "main_money_net_inflow_share"
    else:
        result["main_large_order_net_inflow_share_source"] = "main_large_order_net_inflow_share"
    return result


def _crowded_rows(panel: pl.DataFrame, config: QuantBriefConfig) -> list[dict[str, Any]]:
    rows = []
    for row in _panel_rows(panel):
        crowding = _crowding_temperature(row)
        tcr = _as_float(row.get("tcr"))
        if row.get("status") != "ok":
            continue
        if _gte(crowding, config.crowding_temperature) or _gte(tcr, config.industry_tcr_warning):
            reason = (
                "拥挤温度达到排雷阈值。"
                if _gte(crowding, config.crowding_temperature)
                else f"行业 TCR 达到 {config.industry_tcr_warning:.0f}% 观察线。"
            )
            rows.append(_sector_item(row, source_group="crowding", reason=reason))
    rows.sort(
        key=lambda item: (
            _as_float(item.get("crowding_temperature")) or -1,
            _as_float(item.get("tcr")) or -1,
        ),
        reverse=True,
    )
    return rows


def _sector_item(row: dict[str, Any], *, source_group: str, reason: str) -> dict[str, Any]:
    return {
        "industry_code": row.get("industry_code"),
        "industry_name": row.get("industry_name") or row.get("industry_code") or "",
        "structure_score": _as_float(row.get("structure_score")),
        "structure_rank": row.get("structure_rank"),
        "momentum_score": _as_float(row.get("momentum_score")),
        "valuation_score": _as_float(row.get("valuation_score")),
        "fundamental_score": _as_float(row.get("fundamental_score")),
        "fund_flow_score": _as_float(row.get("fund_flow_score")),
        "return_20d": _as_float(row.get("return_20d")),
        "return_60d": _as_float(row.get("return_60d")),
        "crowding_temperature": _crowding_temperature(row),
        "tcr": _as_float(row.get("tcr")),
        "tags": str(row.get("tags") or ""),
        "source_group": source_group,
        "reason": reason,
    }


def _fund_flow_confirmed(row: dict[str, Any]) -> bool:
    if "资金确认" in str(row.get("tags") or ""):
        return True
    flow_score = _as_float(row.get("fund_flow_score"))
    inflow = _as_float(row.get("money_net_inflow_share_20d"))
    return flow_score is not None and flow_score >= 70 and inflow is not None and inflow > 0


def _crowding_temperature(row: dict[str, Any]) -> float | None:
    value = _as_float(row.get("crowding_temperature"))
    return value if value is not None else _as_float(row.get("tcr_percentile"))


def _dimension_temperatures(scores: dict[str, Any]) -> dict[str, float | None]:
    dimensions = scores.get("dimensions")
    if not isinstance(dimensions, list):
        return {}
    return {
        str(item.get("dimension_id")): _as_float(item.get("temperature"))
        for item in dimensions
        if isinstance(item, dict) and item.get("dimension_id")
    }


def _composite_temperature(scores: dict[str, Any]) -> float | None:
    composite = _mapping(scores.get("composite"))
    return _as_float(composite.get("temperature"))


def _panel_rows(panel: pl.DataFrame) -> list[dict[str, Any]]:
    return [] if panel.is_empty() else panel.to_dicts()


def _flag(flag_id: str, severity: str, message: str) -> dict[str, str]:
    return {"id": flag_id, "severity": severity, "message": message}


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _gte(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _value_text(value: object) -> str:
    numeric = _as_float(value)
    return "-" if numeric is None else f"{numeric:.2f}"


def _date_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
