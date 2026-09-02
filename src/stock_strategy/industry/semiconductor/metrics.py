"""回测统计指标（CAGR / MaxDD / Sharpe）。

对齐 `scripts/industry_semi_supply_legs_backtest.py::_metrics` 口径：
- CAGR：期末净值年化（252 交易日/年）；
- MaxDD：净值序列最大回撤（百分比）；
- Sharpe：日收益均值/样本标准差 × sqrt(252)（无风险利率 0）。
"""

from __future__ import annotations

import math

import polars as pl

_TRADING_DAYS = 252


def compute_metrics(nav: list[float], trading_days: int = _TRADING_DAYS) -> dict[str, float]:
    """从净值序列计算 CAGR / MaxDD / Sharpe。"""
    arr = [v if v > 0 else 1e-9 for v in nav]
    if len(arr) < 2:
        return {"cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0}

    final, n = arr[-1], len(arr)
    years = max(n / max(trading_days, 1), 1e-9)
    cagr = ((final / arr[0]) ** (1.0 / years) - 1.0) * 100.0 if arr[0] > 0 else 0.0

    peak, max_dd = -1e9, 0.0
    for value in arr:
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak)

    rets = [arr[i] / arr[i - 1] - 1.0 for i in range(1, len(arr)) if arr[i - 1] > 0]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var = sum((r - mean_r) ** 2 for r in rets) / max(len(rets) - 1, 1) if len(rets) > 1 else 0.0
    sharpe = mean_r / math.sqrt(var) * math.sqrt(max(trading_days, 1)) if var > 0 else 0.0
    return {"cagr": cagr, "max_dd": max_dd * 100.0, "sharpe": sharpe}


def nav_from_weighted_returns(returns: pl.Series) -> pl.Series:
    """把日收益序列转净值（复利）。"""
    return (1 + returns).cum_prod()


__all__ = ["compute_metrics", "nav_from_weighted_returns"]
