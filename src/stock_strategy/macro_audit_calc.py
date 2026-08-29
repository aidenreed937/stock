"""宏观风控多策略跨周期稳定性审计指标计算器。"""

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
            sharpe = (ann_ret - 0.015) / vol if vol > 1e-8 else 0.0
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
    """计算各极端危机区间的最大回撤与恢复天数。"""
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

            recovery_days = 0
            post_df = wide_df.filter(pl.col("trade_date") >= c_start)
            post_navs = post_df[col].to_list()
            recovered = False
            for idx, pv in enumerate(post_navs):
                if pv >= first_val and idx > 0:
                    recovery_days = idx
                    recovered = True
                    break
            if not recovered:
                recovery_days = len(post_navs)

            rows.append(
                {
                    "压力测试情景": c_name,
                    "危机区间": f"{c_start} ~ {c_end}",
                    "场景特征": c_desc,
                    "标的/策略": col,
                    "区间跌幅": tot_drop,
                    "区间最深回撤": max_dd,
                    "回本所需天数": recovery_days,
                }
            )
    return pd.DataFrame(rows)


def compute_rolling_stats(
    wide_df: pl.DataFrame,
    cols: list[str] | None = None,
    windows: tuple[int, ...] = (252, 756),
    window_days: int | None = None,
) -> pd.DataFrame:
    """计算滚动持有期收益率、胜率与夏普比率分布。"""
    if window_days is not None:
        windows = (window_days,)
    if cols is None:
        cols = [c for c in wide_df.columns if c != "trade_date"]

    rows: list[dict[str, Any]] = []
    bench_col = "中证全指" if "中证全指" in cols else cols[0]
    for w in windows:
        w_label = f"滚动 {w // 252} 年 ({w}D)" if w % 252 == 0 else f"{w} 交易日"
        bench_navs = wide_df[bench_col].to_numpy() if bench_col in wide_df.columns else None
        for col in cols:
            navs = wide_df[col].to_numpy()
            if len(navs) <= w:
                continue
            rets = (navs[w:] / navs[:-w]) - 1.0
            pos_ratio = float(np.mean(rets > 0)) if len(rets) > 0 else 0.0
            mean_ret = float(np.mean(rets)) if len(rets) > 0 else 0.0
            median_ret = float(np.median(rets)) if len(rets) > 0 else 0.0
            p5 = float(np.percentile(rets, 5)) if len(rets) > 0 else 0.0
            p95 = float(np.percentile(rets, 95)) if len(rets) > 0 else 0.0

            win_bench = 0.0
            if bench_navs is not None and len(bench_navs) > w:
                bench_rets = (bench_navs[w:] / bench_navs[:-w]) - 1.0
                win_bench = float(np.mean(rets >= bench_rets)) if len(rets) > 0 else 0.0

            rows.append(
                {
                    "滚动窗口": w_label,
                    "标的/策略": col,
                    "测试窗口总数": len(rets),
                    "正收益胜率": pos_ratio,
                    "跑赢基准(全指)概率": win_bench,
                    "平均收益率": mean_ret,
                    "中位数收益率": median_ret,
                    "最佳区间收益": p95,
                    "最差区间收益": p5,
                    "极端最深回撤": p5,
                }
            )
    return pd.DataFrame(rows)


__all__ = ["compute_rolling_stats", "compute_slice_metrics", "compute_stress_test"]
