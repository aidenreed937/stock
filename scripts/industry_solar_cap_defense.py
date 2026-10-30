"""光伏 630500 需求腿「贴顶防守」验证。

背景：630500 各候选供给腿样本外 2022+ 全部失效（industry_solar_supply_legs_backtest.py）。
需求腿（光伏装机）逐年 IC 多为正（2019/2020/2021/2023/2025/2026），但粗聚合 OOS 转负——
机制假设为「分位贴顶反身」：装机需求分位冲到历史高位后，未来 60 日容易反噬。

本脚本显式验证：
1. 装机分位分层（贴顶区 vs 中低位）的 fwd60 收益分布（均值/中位/上涨率）对比；
2. 防守变体（需求分位 ≥ 阈值 → 降仓/空仓）vs 纯买入的 CAGR/Sharpe/MaxDD，T+1 无前视；
3. 样本外 2022+ 是否成立（不是全样本刷参数）。

口径（对齐仓库 series）：
- demand leg = solar_capacity.monthly_new_capacity_3mma → _monthly_pct(yoy→36月分位) → release_date 生效前向填充；
- 收益 = 630500 close pct_change，fwd60 = f60；
- T+1：信号当日权重，次日收益生效（weight.shift(1)）。

输出：data/analytics/industry_strategy/industry_solar_cap_defense.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl
from industry_direction_map import _monthly_pct
from scipy import stats

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "630500"


def _load() -> pl.DataFrame:
    df = pl.read_parquet("data/curated/industry/solar_capacity.parquet").select(
        ["trade_date", "release_date", "monthly_new_capacity_3mma"]
    )
    leg = _monthly_pct(df, "monthly_new_capacity_3mma", window_months=36)  # 列名 pct
    panel = pl.read_parquet(_PANEL)
    panel = panel.filter(
        (pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START)
    ).sort("trade_date")
    daily = (
        panel.select(["trade_date"])
        .join(leg.select(["trade_date", "pct"]), on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("pct").fill_null(strategy="forward"))
    )
    return (
        panel.select(["trade_date", "close"])
        .join(daily.select(["trade_date", "pct"]), on="trade_date", how="left")
        .with_columns(
            pl.col("close").pct_change().fill_null(0.0).alias("ret"),
            (pl.col("close").shift(-60) / pl.col("close") - 1.0).alias("f60"),
        )
    )


def _metrics(nav: list[float]) -> dict[str, float]:
    arr = [v if v > 0 else 1e-9 for v in nav]
    if len(arr) < 2:
        return {"cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0}
    years = max(len(arr) / 252.0, 1e-9)
    cagr = ((arr[-1] / arr[0]) ** (1.0 / years) - 1.0) * 100.0 if arr[0] > 0 else 0.0
    peak, mdd = -1e9, 0.0
    for v in arr:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    rets = [arr[i] / arr[i - 1] - 1.0 for i in range(1, len(arr)) if arr[i - 1] > 0]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var = sum((r - mean_r) ** 2 for r in rets) / max(len(rets) - 1, 1) if len(rets) > 1 else 0.0
    sharpe = mean_r / math.sqrt(var) * math.sqrt(252.0) if var > 0 else 0.0
    return {"cagr": cagr, "max_dd": mdd * 100.0, "sharpe": sharpe}


def _run(mode: str, df: pl.DataFrame, thr: int) -> tuple[dict[str, float], dict[str, float]]:
    """weight.shift(1) 严格 T+1：当日信号，次日执行。"""
    if mode == "buy":
        w = pl.Series([1.0] * len(df))
    elif mode == "degrade":  # pct>=thr 降仓 30%
        w = pl.Series([0.3 if p is not None and p >= thr else 1.0 for p in df["pct"].to_list()])
    elif mode == "flat":  # pct>=thr 空仓
        w = pl.Series([0.0 if p is not None and p >= thr else 1.0 for p in df["pct"].to_list()])
    else:
        w = pl.Series([1.0] * len(df))
    w_shift = w.shift(1).fill_null(1.0)
    pos = (w_shift * df["ret"].fill_null(0.0)).to_list()
    full = _metrics((1 + pl.Series(pos)).cum_prod().to_list())
    oos_df = df.filter(pl.col("trade_date") >= _OOS)
    # 对 OOS 重新计算权重
    if mode == "buy":
        wo = pl.Series([1.0] * len(oos_df))
    elif mode == "degrade":
        wo = pl.Series(
            [0.3 if p is not None and p >= thr else 1.0 for p in oos_df["pct"].to_list()]
        )
    else:
        wo = pl.Series(
            [0.0 if p is not None and p >= thr else 1.0 for p in oos_df["pct"].to_list()]
        )
    wo_shift = wo.shift(1).fill_null(1.0)
    pos_oos = (wo_shift * oos_df["ret"].fill_null(0.0)).to_list()
    oos = _metrics((1 + pl.Series(pos_oos)).cum_prod().to_list())
    return full, oos


def main() -> None:
    df = _load().drop_nulls("pct")
    print("=== 装机需求分位分层 fwd60 分布（全体）===")
    # Spearman IC by bucket
    for lo, hi, label in [(None, 80, "中低位 <80"), (80, None, "贴顶区 ≥80")]:
        m = df
        if lo is not None:
            m = m.filter(pl.col("pct") >= lo)
        if hi is not None:
            m = m.filter(pl.col("pct") < hi)
        m = m.drop_nulls("f60")
        if len(m) < 20:
            print(f"{label}: n<20 跳过")
            continue
        vals = m["f60"].to_list()
        mean = sum(vals) / len(vals) * 100
        med = sorted(vals)[len(vals) // 2] * 100
        up = sum(1 for v in vals if v > 0) / len(vals) * 100
        ic, _ = stats.spearmanr(m["pct"].to_list(), m["f60"].to_list())
        print(
            f"  {label}: n={len(m)} fwd60均值={mean:.2f}% 中位={med:.2f}% 上涨率={up:.1f}% 组内IC={ic:.3f}"
        )

    # 样本外分层
    print("\n=== 样本外 2022+ 分层 ===")
    for lo, hi, label in [(None, 80, "中低位 <80"), (80, None, "贴顶区 ≥80")]:
        m = df.filter(pl.col("trade_date") >= _OOS)
        if lo is not None:
            m = m.filter(pl.col("pct") >= lo)
        if hi is not None:
            m = m.filter(pl.col("pct") < hi)
        m = m.drop_nulls("f60")
        if len(m) < 20:
            print(f"{label}: n<20 跳过")
            continue
        vals = m["f60"].to_list()
        mean = sum(vals) / len(vals) * 100
        med = sorted(vals)[len(vals) // 2] * 100
        up = sum(1 for v in vals if v > 0) / len(vals) * 100
        print(f"  {label}: n={len(m)} fwd60均值={mean:.2f}% 中位={med:.2f}% 上涨率={up:.1f}%")

    print("\n=== 防守变体 vs 纯买入（T+1）===")
    headers = f"{'变体':32s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s}"
    print(headers)
    for mode, thr, label in [
        ("buy", 0, "纯买入(基准)"),
        ("degrade", 80, "降仓30% 阈值80"),
        ("degrade", 70, "降仓30% 阈值70"),
        ("flat", 80, "空仓 阈值80"),
        ("flat", 85, "空仓 阈值85"),
    ]:
        full, oos = _run(mode, df, thr)
        print(
            f"{label:32s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
            f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f}"
        )

    # 逐年 MaxDD 对照（防守是否年年优于买入）——关键稳健性
    print("\n=== 逐年 MaxDD：买入 vs 降仓80（全周期）===")
    buy = df.with_columns(pl.Series([1.0] * len(df)).alias("w")).with_columns(
        (pl.col("w").shift(1).fill_null(1.0) * pl.col("ret")).alias("pos")
    )
    degr = df.with_columns(
        pl.Series([0.3 if p is not None and p >= 80 else 1.0 for p in df["pct"].to_list()]).alias(
            "w"
        )
    ).with_columns((pl.col("w").shift(1).fill_null(1.0) * pl.col("ret")).alias("pos"))
    for y in sorted(set(d.year for d in df["trade_date"].to_list())):

        def dd(series):
            arr = [0.0 if v is None else v for v in series.to_list()]
            peak, m = -1e9, 0.0
            acc = 1.0
            for v in arr:
                acc *= 1 + v
                peak = max(peak, acc)
                m = max(m, (peak - acc) / peak)
            return m * 100

        sub_b = buy.filter(pl.col("trade_date").dt.year() == y)["pos"]
        sub_d = degr.filter(pl.col("trade_date").dt.year() == y)["pos"]
        print(f"  {y}: 买入MaxDD={dd(sub_b):.1f}%  降仓80MaxDD={dd(sub_d):.1f}%")


if __name__ == "__main__":
    main()
