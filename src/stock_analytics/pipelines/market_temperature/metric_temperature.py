"""原始指标值到温度刻度的转换。"""

from __future__ import annotations

from math import erf, sqrt
from typing import Any


def fact_temperature(row: dict[str, Any], direction: str) -> float | None:
    """将指标事实行转换为 0-100 温度，并按方向取正向或反向。"""
    value = row.get("value_float")
    if value is None:
        return None
    metric_id = str(row["metric_id"])
    numeric = float(value)
    is_percentile_temperature = metric_id == "valuation_temperature" or "percentile" in metric_id
    if row.get("unit") == "temperature" or is_percentile_temperature:
        temperature = numeric
    elif "zscore" in metric_id:
        temperature = normal_cdf(numeric) * 100.0
    elif metric_id == "rsi_14d":
        temperature = numeric
    elif metric_id in {
        "advance_share",
        "above_ma20_share",
        "above_ma60_share",
        "above_ma120_share",
        "new_high_share_252d",
        "new_low_share_252d",
    }:
        temperature = numeric * 100.0
    elif metric_id in {"return_20d", "ma_bias_20d", "margin_balance_growth_20d"}:
        temperature = 50.0 + numeric * 500.0
    elif metric_id in {"main_money_net_inflow_share", "super_large_net_inflow_share"}:
        temperature = 50.0 + numeric * 1000.0
    else:
        return None
    return apply_direction(temperature, direction)


def apply_direction(value: float, direction: str) -> float:
    """按指标方向计算温度，反向指标以 100 - value 折算。"""
    temperature = 100.0 - value if direction == "inverse" else value
    return clip_temperature(temperature)


def clip_temperature(value: float) -> float:
    """将温度限制在 0-100 区间。"""
    return round(min(100.0, max(0.0, value)), 2)


def normal_cdf(value: float) -> float:
    """标准正态累积分布函数。"""
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))
