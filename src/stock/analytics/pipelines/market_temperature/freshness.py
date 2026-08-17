"""市场温度计评分数据新鲜度统计。

进入评分的指标以 note 中的 stale_days 与数据日期为据，输出维度与全局
数据新鲜度结构，供评分结构披露与简报时效提示使用。
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from stock.analytics.pipelines.market_temperature.config import DimensionConfig

_METRIC_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_STALE_DAYS_PATTERN = re.compile(r"stale_days=(\d+)")


def dimension_freshness(
    facts: pl.DataFrame,
    dimension_id: str,
    metric_ids: set[str],
    item: DimensionConfig,
) -> dict[str, Any]:
    """统计该维度进入评分的指标的数据日期新鲜度。"""
    rows = metric_fact_rows(facts, dimension_id, metric_ids)
    latest: date | None = None
    stale_entries: list[dict[str, str]] = []
    for row in rows:
        data_date = latest_date_in_note(str(row.get("note") or ""))
        if data_date is not None and (latest is None or data_date > latest):
            latest = data_date
        if item.stale_after_days is not None and is_stale_metric(row, item):
            stale_entries.append(
                {
                    "metric_id": str(row["metric_id"]),
                    "data_date": data_date.isoformat() if data_date is not None else "",
                }
            )
    return {
        "latest_data_date": latest.isoformat() if latest is not None else None,
        "stale_metric_count": len(stale_entries),
        "stale_metrics": stale_entries,
    }


def composite_freshness(dimensions: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总各维度进入评分且数据陈旧的指标。"""
    stale_entries: list[dict[str, str]] = []
    for item in dimensions:
        freshness = item.get("data_freshness") or {}
        for entry in freshness.get("stale_metrics", []):
            stale_entries.append(
                {
                    "metric_id": str(entry.get("metric_id") or ""),
                    "data_date": str(entry.get("data_date") or ""),
                    "dimension": str(item.get("dimension_id") or ""),
                }
            )
    stale_entries = [entry for entry in stale_entries if entry["metric_id"]]
    return {
        "stale_metric_count": len(stale_entries),
        "stale_metrics": stale_entries,
    }


def metric_fact_rows(
    facts: pl.DataFrame,
    dimension_id: str,
    metric_ids: set[str],
) -> list[dict[str, Any]]:
    """返回该维度进入评分且状态为 ok 的指标事实行。"""
    if facts.is_empty() or not metric_ids:
        return []
    return facts.filter(
        (pl.col("dimension") == dimension_id)
        & (pl.col("category") == "metric_value")
        & (pl.col("status") == "ok")
        & (pl.col("metric_id").is_in(metric_ids))
    ).to_dicts()


def is_stale_metric(row: dict[str, Any], item: DimensionConfig) -> bool:
    """判断指标数据日期是否超过维度配置的新鲜度阈值。"""
    if item.stale_after_days is None:
        return False
    stale_days = stale_days_in_note(str(row.get("note") or ""))
    return stale_days is not None and stale_days > item.stale_after_days


def stale_days_in_note(note: str) -> int | None:
    """从指标 note 中解析 stale_days=NN 标记。"""
    match = _STALE_DAYS_PATTERN.search(note)
    return int(match.group(1)) if match else None


def latest_date_in_note(note: str) -> date | None:
    """从指标 note 中提取最新数据日期。"""
    dates = [
        value
        for value in (_parse_metric_date(item) for item in _METRIC_DATE_PATTERN.findall(note))
        if value is not None
    ]
    return max(dates) if dates else None


def _parse_metric_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
