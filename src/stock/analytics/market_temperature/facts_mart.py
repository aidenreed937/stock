"""市场温度计与 FeatureStore / Analytics Mart 的指标事实转换器。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl

from stock.analytics.metrics.calculators.percentile import percentile_rank

if TYPE_CHECKING:
    from collections.abc import Iterable

    from stock.analytics.market_temperature.config import MetricInputConfig

_MARKET_DAILY_COLUMN_MAP: dict[str, str] = {
    "advance_share": "advance_ratio",
    "adv_dec_ratio": "adv_dec_ratio",
    "advance_ratio": "advance_ratio",
    "above_ma20_share": "above_ma20_ratio",
    "above_ma20_ratio": "above_ma20_ratio",
    "above_ma60_share": "above_ma60_ratio",
    "above_ma60_ratio": "above_ma60_ratio",
    "above_ma120_share": "above_ma120_ratio",
    "above_ma120_ratio": "above_ma120_ratio",
    "new_high_252d_ratio": "new_high_252d_ratio",
    "new_low_252d_ratio": "new_low_252d_ratio",
    "margin_buy_share": "margin_buy_ratio",
    "margin_buy_ratio": "margin_buy_ratio",
    "margin_balance": "margin_balance",
    "margin_penetration": "margin_penetration",
    "market_turnover_rate": "market_turnover_rate",
    "main_money_net_inflow_share": "main_net_inflow_ratio",
    "main_net_inflow_ratio": "main_net_inflow_ratio",
    "market_amount": "total_turnover",
    "total_turnover": "total_turnover",
}


def _calc_percentile_metric(filtered: pl.DataFrame, metric_id: str) -> float | None:
    col_map = {
        "market_amount_percentile_1250d": "total_turnover",
        "turnover_rate_percentile_1250d": "market_turnover_rate",
        "margin_penetration_percentile_1250d": "margin_penetration",
    }
    col = col_map.get(metric_id)
    if col and col in filtered.columns:
        series = filtered[col].drop_nulls()
        if not series.is_empty():
            return percentile_rank(series.tail(1250), 1250)
    return None


def _calc_zscore_or_growth(filtered: pl.DataFrame, metric_id: str) -> float | None:
    if metric_id == "margin_buy_share_zscore_60d" and "margin_buy_ratio" in filtered.columns:
        series = filtered["margin_buy_ratio"].drop_nulls()
        if len(series) >= 30:
            w = series.tail(60)
            m, s = w.mean(), w.std()
            return float((w[-1] - m) / s) if s and m is not None else 0.0
    elif metric_id == "margin_balance_growth_20d" and "margin_balance" in filtered.columns:
        series = filtered["margin_balance"].drop_nulls()
        if len(series) >= 21 and (prior := float(series[-21])) > 0:
            return float((series[-1] - prior) / prior)
    return None


def _compute_rolling_fact_value(filtered: pl.DataFrame, metric_id: str) -> float | None:
    """从 market_daily 历史序列计算滚动分位/Z-Score/增长率。"""
    pct = _calc_percentile_metric(filtered, metric_id)
    if pct is not None:
        return pct
    return _calc_zscore_or_growth(filtered, metric_id)


def try_get_market_daily_fact(
    market_daily: pl.DataFrame,
    dimension: str,
    metric: MetricInputConfig,
    as_of_date: date,
) -> dict[str, Any] | None:
    """尝试直接从已物化的 market_daily 宽表中提取或计算指标事实。"""
    if market_daily.is_empty():
        return None

    filtered = market_daily.filter(pl.col("trade_date") <= as_of_date)
    if filtered.is_empty():
        return None

    latest_row = filtered.tail(1)
    latest_date = latest_row["trade_date"][0]

    # 1. 尝试计算滚动特征
    rolling_val = _compute_rolling_fact_value(filtered, metric.metric_id)
    if rolling_val is not None:
        return {
            "fact_id": f"metric.{dimension}.{metric.metric_id}",
            "category": "metric_value",
            "dimension": dimension,
            "data_source": "mart",
            "dataset": "market_daily",
            "as_of_date": as_of_date,
            "window": 0,
            "metric_id": metric.metric_id,
            "value_float": float(rolling_val),
            "value_text": "",
            "unit": "raw",
            "sample_size": filtered.height,
            "source": "FeatureStore.market_daily",
            "status": "ok",
            "note": f"source=mart.market_daily; metric_date={latest_date.isoformat()}",
        }

    # 2. 尝试直接列映射
    col_name = _MARKET_DAILY_COLUMN_MAP.get(metric.metric_id)
    if not col_name or col_name not in market_daily.columns:
        return None

    val = latest_row[col_name][0]
    if val is None:
        return None

    return {
        "fact_id": f"metric.{dimension}.{metric.metric_id}",
        "category": "metric_value",
        "dimension": dimension,
        "data_source": "mart",
        "dataset": "market_daily",
        "as_of_date": as_of_date,
        "window": 0,
        "metric_id": metric.metric_id,
        "value_float": float(val),
        "value_text": "",
        "unit": "raw",
        "sample_size": filtered.height,
        "source": "FeatureStore.market_daily",
        "status": "ok",
        "note": f"source=mart.market_daily; metric_date={latest_date.isoformat()}",
    }


def parse_date_value(value: object) -> date | None:
    """解析字符串或日期对象为 date。"""
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
    if len(text) >= 6 and text[:6].isdigit():
        year = int(text[:4])
        month = int(text[4:6])
        return date(year, month, 1)
    return date.fromisoformat(text[:10])


def date_values(values: Iterable[object]) -> list[date]:
    """批量解析日期列表。"""
    dates: list[date] = []
    for value in values:
        parsed = parse_date_value(value)
        if parsed is not None:
            dates.append(parsed)
    return dates
