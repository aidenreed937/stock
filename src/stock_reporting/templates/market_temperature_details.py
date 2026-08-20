"""市场温度计报告的事实摘要与细节渲染辅助函数。"""

from __future__ import annotations

from typing import Any

import polars as pl

import stock_reporting.templates.input_validation as _input_validation
from stock_reporting.interpretation.market_temperature.interpretation import (
    get_dimension_comment as _dimension_comment,
)


def summarize_facts(facts: pl.DataFrame) -> dict[str, Any]:
    """汇总事实并保留指标实际日期。"""
    summary = _input_validation.summarize_facts(facts, _input_validation.MARKET_FACT_COLUMNS)
    if facts.is_empty() or "metric_id" not in facts.columns:
        return summary
    metric_rows = facts.filter(pl.col("category") == "metric_value").to_dicts()
    summary["metric_values"] = [
        {
            "dimension": row.get("dimension"),
            "metric_id": row.get("metric_id"),
            "value_float": row.get("value_float"),
            "status": row.get("status"),
            "metric_date": _date_text(row.get("metric_date")),
        }
        for row in metric_rows
    ]
    return summary


def dimension_interpretation_comment(item: dict[str, Any]) -> str:
    """组合维度基础解读与情绪子口径摘要。"""
    dimension_id = str(item.get("dimension_id") or "")
    comment = _dimension_comment(dimension_id, item.get("temperature"))
    subgroup = subgroup_text(item)
    return f"{comment}；{subgroup}" if subgroup != "-" else comment


def subgroup_text(item: dict[str, Any]) -> str:
    """格式化情绪维度的子口径温度。"""
    subgroups = item.get("subgroups")
    if not isinstance(subgroups, dict):
        return "-"
    activity = _as_float(subgroups.get("activity"))
    slow = _as_float(subgroups.get("slow"))
    if activity is None and slow is None:
        return "-"
    source = str(item.get("temperature_source") or "daily")
    daily = item.get("temperature") if source == "daily" else None
    return (
        f"动能 {_temperature_text(daily)} / "
        f"活跃水位 {_temperature_text(activity)} / "
        f"慢情绪 {_temperature_text(slow)}"
    )


def structured_drivers_section(
    *,
    drivers: dict[str, Any],
    previous_manifest: dict[str, Any] | None,
    current_manifest: dict[str, Any],
) -> list[str]:
    """渲染结构化跨期驱动表。"""
    previous_date = str(
        drivers.get("comparison_as_of") or (previous_manifest or {}).get("as_of_date") or "前期"
    )
    current_date = str(current_manifest.get("as_of_date") or "本期")
    lines = [
        "## 跨期驱动变化",
        "",
        f"- 对比基准: {previous_date} -> {current_date}",
        f"- 结构化摘要: {drivers.get('summary') or '暂无驱动摘要'}",
        "",
        "| 驱动维度 | 温度变化 | 加权贡献 | 方向 |",
        "|---|---:|---:|---|",
    ]
    composite_delta = _as_float(drivers.get("composite_delta"))
    lines.append(f"| 综合温度 | {_delta_text(composite_delta)} | - | - |")
    for item in drivers.get("top_contributors", []):
        if not isinstance(item, dict):
            continue
        delta = _as_float(item.get("delta"))
        weighted_delta = _as_float(item.get("weighted_delta"))
        direction = "升温" if item.get("direction") == "warming" else "降温"
        lines.append(
            f"| {item.get('name') or item.get('dimension_id')} | "
            f"{_delta_text(delta)} | {_delta_text(weighted_delta)} | {direction} |"
        )
    lines.append("")
    return lines


def score_composite_temperature(scores: dict[str, Any]) -> float | None:
    """读取报告评分中的综合温度。"""
    composite = scores.get("composite", {})
    if not isinstance(composite, dict):
        return None
    return _as_float(composite.get("temperature"))


def format_fact_metric_value(metric_id: str, value_float: float | None) -> str:
    """按指标语义格式化人工报告中的事实值。"""
    if value_float is None:
        return "-"
    if metric_id in {
        "margin_balance_growth_20d",
        "margin_balance_growth_60d",
        "main_money_net_inflow_share",
        "main_money_net_inflow_share_20d_cum",
        "main_large_order_net_inflow_share",
        "super_large_net_inflow_share",
        "advance_share",
        "above_ma20_share",
        "above_ma60_share",
        "return_20d",
    }:
        if metric_id in {
            "margin_balance_growth_20d",
            "margin_balance_growth_60d",
            "main_money_net_inflow_share",
            "main_money_net_inflow_share_20d_cum",
            "main_large_order_net_inflow_share",
            "super_large_net_inflow_share",
            "return_20d",
        }:
            return f"{value_float * 100:+.2f}%"
        return f"{value_float * 100:.2f}%"

    if metric_id in {
        "fs_profit_growth_temperature",
        "forecast_positive_temperature",
        "report_revision_temperature",
    }:
        return f"{value_float:.2f}%"

    sem = _metric_band_semantic(metric_id, value_float)
    return f"{value_float:.2f} ({sem})" if sem else f"{value_float:.2f}"


def _metric_band_semantic(metric_id: str, value: float) -> str:
    if "pressure" in metric_id:
        bands = ((80.0, "高压力"), (60.0, "中高压力"), (40.0, "中性"), (20.0, "低压力"))
        default_label = "压力极低"
    elif "percentile" in metric_id or "temperature" in metric_id or metric_id == "rsi_14d":
        bands = ((85.0, "极高"), (70.0, "偏高"), (40.0, "中性"), (20.0, "偏低"))
        default_label = "极低"
    else:
        return ""
    for threshold, label in bands:
        if value >= threshold:
            return label
    return default_label


def _date_text(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _temperature_text(value: object) -> str:
    numeric = _as_float(value)
    return "不可判定" if numeric is None else f"{numeric:.2f}"


def _delta_text(value: float | None) -> str:
    return "不可判定" if value is None else f"{value:+.2f}"


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None
