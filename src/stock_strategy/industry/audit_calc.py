"""申万行业多策略跨周期稳定性审计指标计算器。

负责生产级计算：
1. 跨 6 大宏观范式分段回溯切片指标；
2. 历史 4 大极端危机压力测试情景指标；
3. 任意时点滚动 1 年 (252D) 与 3 年 (756D) 胜率与回撤分布统计。
"""

from __future__ import annotations

from datetime import date
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd
import polars as pl

_TRADING_DAYS_PER_YEAR = 252.0


def compute_slice_metrics(slice_df: pl.DataFrame, cols: list[str]) -> dict[str, dict[str, float]]:
    """计算切片区间内各列的累计收益、年化收益与最大回撤。"""
    res: dict[str, dict[str, float]] = {}
    n = len(slice_df)
    if n < 2:
        return {
            c: {
                "total_return": 0.0,
                "annualized_return": 0.0,
                "cagr": 0.0,
                "max_drawdown": 0.0,
                "volatility": 0.0,
                "sharpe": 0.0,
            }
            for c in cols
        }

    years = n / _TRADING_DAYS_PER_YEAR
    for c in cols:
        navs = slice_df[c].to_list()
        first_nav = float(navs[0]) if navs[0] > 0 else 1.0
        final_nav = float(navs[-1])
        tot_ret = (final_nav / first_nav) - 1.0
        ann_ret = (
            (final_nav / first_nav) ** (1.0 / years) - 1.0 if years > 0 and final_nav > 0 else 0.0
        )

        peak = navs[0]
        max_dd = 0.0
        for v in navs:
            peak = max(peak, v)
            dd = (v - peak) / peak if peak > 0 else 0.0
            max_dd = min(max_dd, dd)

        rets = [(navs[i] / navs[i - 1] - 1.0) for i in range(1, n)]
        if rets:
            mean_r = sum(rets) / len(rets)
            var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)
            vol = sqrt(var_r) * sqrt(_TRADING_DAYS_PER_YEAR)
            sharpe = (ann_ret - 0.02) / vol if vol > 1e-8 else 0.0
        else:
            vol, sharpe = 0.0, 0.0

        res[c] = {
            "total_return": tot_ret,
            "annualized_return": ann_ret,
            "cagr": ann_ret,
            "max_drawdown": max_dd,
            "volatility": vol,
            "sharpe": sharpe,
        }
    return res


def compute_stress_test(
    wide_df: pl.DataFrame, cols: list[str], crisis_periods: list[tuple[str, date, date, str]]
) -> pd.DataFrame:
    """计算各极端危机区间的最大回撤与跌幅。"""
    rows: list[dict[str, Any]] = []
    for c_name, c_start, c_end, c_desc in crisis_periods:
        sub = wide_df.filter((pl.col("trade_date") >= c_start) & (pl.col("trade_date") <= c_end))
        if sub.is_empty():
            continue
        for col in cols:
            navs = sub[col].to_list()
            peak = navs[0]
            max_dd = 0.0
            for v in navs:
                peak = max(peak, v)
                dd = (v - peak) / peak if peak > 0 else 0.0
                max_dd = min(max_dd, dd)

            first_val = navs[0]
            final_val = navs[-1]
            tot_drop = (final_val / first_val - 1.0) if first_val > 0 else 0.0

            rows.append(
                {
                    "crisis_name": c_name,
                    "description": c_desc,
                    "strategy": col,
                    "period_return": round(tot_drop * 100.0, 2),
                    "max_drawdown": round(abs(max_dd) * 100.0, 2),
                }
            )
    return pd.DataFrame(rows)


def compute_rolling_stats(wide_df: pl.DataFrame, cols: list[str], window: int) -> pd.DataFrame:
    """计算滚动持有窗口的年化收益率、胜率与最大回撤分布。"""
    rows: list[dict[str, Any]] = []
    n = len(wide_df)
    if n <= window:
        return pd.DataFrame(rows)

    years = window / _TRADING_DAYS_PER_YEAR
    for col in cols:
        navs = np.array(wide_df[col].to_list(), dtype=float)
        roll_rets: list[float] = []
        roll_dds: list[float] = []

        for i in range(n - window):
            sub = navs[i : i + window]
            first_v = sub[0]
            last_v = sub[-1]
            cagr = (
                ((last_v / first_v) ** (1.0 / years) - 1.0) if first_v > 0 and last_v > 0 else 0.0
            )
            roll_rets.append(cagr)

            # 该窗口内最大回撤
            pk = sub[0]
            mdd = 0.0
            for val in sub:
                pk = max(pk, val)
                dd = (val - pk) / pk if pk > 0 else 0.0
                mdd = min(mdd, dd)
            roll_dds.append(abs(mdd))

        r_arr = np.array(roll_rets)
        d_arr = np.array(roll_dds)
        win_rate = float(np.mean(r_arr > 0.0)) * 100.0 if len(r_arr) > 0 else 0.0

        rows.append(
            {
                "strategy": col,
                "window_days": window,
                "win_rate": round(win_rate, 1),
                "cagr_mean": round(float(np.mean(r_arr)) * 100.0, 2) if len(r_arr) > 0 else 0.0,
                "cagr_median": round(float(np.median(r_arr)) * 100.0, 2) if len(r_arr) > 0 else 0.0,
                "cagr_p10": round(float(np.percentile(r_arr, 10)) * 100.0, 2)
                if len(r_arr) > 0
                else 0.0,
                "cagr_p90": round(float(np.percentile(r_arr, 90)) * 100.0, 2)
                if len(r_arr) > 0
                else 0.0,
                "max_drawdown_avg": round(float(np.mean(d_arr)) * 100.0, 2)
                if len(d_arr) > 0
                else 0.0,
                "max_drawdown_worst": round(float(np.max(d_arr)) * 100.0, 2)
                if len(d_arr) > 0
                else 0.0,
            }
        )
    return pd.DataFrame(rows)


__all__ = [
    "compute_rolling_stats",
    "compute_slice_metrics",
    "compute_stress_test",
]
