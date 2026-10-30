"""光伏 630500 财报净利 TTM 同比「拐头（右侧确认）」回测。

问题：630500 无可用 fwd60 供需择时腿。本脚本检验财报层「净利 TTM 同比拐头」能否作为
底部右侧确认（右侧确认 ≠ 前瞻领先，检验的是「拐头后参与」是否优于纯买入，作动量兜底的增强）。

信号（reportDate=披露日生效，无前视，前向填充日频，weight.shift(1) 严格 T+1）：
- buy_hold：纯买入（基准）。
- np_turn：np_ttm_y2y 由负转正（严格拐头）→ 满仓，否则降 30%。
- np_up：np_ttm_y2y 边际改善（本期 > 上一披露期）→ 满仓，否则降 30%。
- np_up_pos：np_ttm_y2y 边际改善 **且为正** → 满仓，否则降 30%（最严，量价齐升式）。

数据：sw_2021_l2_fs_non_financial，symbol=630500，字段 q.ps.np.ttm_y2y。

输出：data/analytics/industry_strategy/industry_solar_profit_turn.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_FIN = Path("data/curated/lixinger/market=CN/sw_2021_l2_fs_non_financial/data.parquet")
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "630500"


def _signal() -> pl.DataFrame:
    """把季频 np 序列转成日频生效信号（按 reportDate 前向填充）。"""
    df = pl.read_parquet(_FIN)
    df = df.filter(
        (pl.col("symbol") == _INDUSTRY)
        & pl.col("standardDate").is_not_null()
        & pl.col("reportDate").is_not_null()
    )
    # 每季度保留一份（去掉年报与季度重复披露的合并，取最新披露日期去重到报告期）
    sub = (
        df.select(
            [
                "standardDate",
                "reportDate",
                pl.col("q")
                .struct.field("ps")
                .struct.field("np")
                .struct.field("ttm_y2y")
                .alias("np"),
            ]
        )
        .sort("standardDate")
        .unique(subset=["standardDate"], keep="last")
    ).sort("reportDate")
    # 计算各信号 → 月/季频布尔（int）
    npv_raw = sub["np"].to_list()
    npv = [0.0 if v is None else float(v) for v in npv_raw]
    res = sub
    res = res.with_columns(
        pl.Series("np_prev", [None] + npv[:-1]),
        pl.Series(
            "turn",
            [0.0] + [1.0 if (npv[i] > 0 and npv[i - 1] <= 0) else 0.0 for i in range(1, len(npv))],
        ),
        pl.Series(
            "up",
            [0.0] + [1.0 if npv[i] > npv[i - 1] else 0.0 for i in range(1, len(npv))],
        ),
        pl.Series(
            "up_pos",
            [0.0]
            + [1.0 if (npv[i] > npv[i - 1] and npv[i] > 0) else 0.0 for i in range(1, len(npv))],
        ),
    )
    # 映射到日频交易日网格
    panel = pl.read_parquet(_PANEL)
    panel = panel.filter(
        (pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START)
    ).sort("trade_date")
    grid = panel.select(["trade_date"])
    sig = (
        grid.join(
            res.select(["reportDate", "turn", "up", "up_pos"]).rename({"reportDate": "trade_date"}),
            on="trade_date",
            how="left",
        )
        .sort("trade_date")
        .with_columns(
            pl.col("turn").fill_null(strategy="forward").fill_null(0.0).alias("turn"),
            pl.col("up").fill_null(strategy="forward").fill_null(0.0).alias("up"),
            pl.col("up_pos").fill_null(strategy="forward").fill_null(0.0).alias("up_pos"),
        )
    )
    return sig


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


def _run(mode: str, panel: pl.DataFrame, sig: pl.DataFrame, col: str) -> tuple[dict, dict]:
    df = (
        panel.select(["trade_date", "close"])
        .join(sig.select(["trade_date", "turn", "up", "up_pos"]), on="trade_date", how="left")
        .with_columns(
            pl.col("close").pct_change().fill_null(0.0).alias("ret"),
            pl.col("close").shift(-60).alias("close_f60"),
        )
        .sort("trade_date")
    )
    if mode == "buy":
        w = pl.Series([1.0] * len(df))
    elif mode in ("turn", "up", "up_pos"):
        s = df[col].fill_null(0.0)
        w = 1.0 * s + 0.3 * (1.0 - s)
    else:
        w = pl.Series([1.0] * len(df))
    w_shift = w.shift(1).fill_null(1.0)
    pos = (w_shift * df["ret"]).fill_null(0.0).to_list()
    full = _metrics((1 + pl.Series(pos)).cum_prod().to_list())
    oos_df = df.filter(pl.col("trade_date") >= _OOS)
    if mode == "buy":
        wo = pl.Series([1.0] * len(oos_df))
    else:
        s = oos_df[col].fill_null(0.0)
        wo = 1.0 * s + 0.3 * (1.0 - s)
    wo_shift = wo.shift(1).fill_null(1.0)
    pos_oos = (wo_shift * oos_df["ret"]).fill_null(0.0).to_list()
    oos = _metrics((1 + pl.Series(pos_oos)).cum_prod().to_list())
    # 持仓天数占比
    hold = (1.0 * w).mean() * 100
    return (full, oos, hold)


def main() -> None:
    panel = pl.read_parquet(_PANEL)
    panel = panel.filter(
        (pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START)
    ).sort("trade_date")
    sig = _signal()
    print(sig.filter(pl.col("trade_date") >= datetime.date(2026, 1, 1)).tail(10))

    variants = [
        ("buy", "纯买入(基准)", "up"),
        ("turn", "净利由负转正(严格拐头) 满仓/降30%", "turn"),
        ("up", "净利边际改善 满仓/降30%", "up"),
        ("up_pos", "边际改善且为正 满仓/降30%", "up_pos"),
    ]
    print("\n=== 630500 财报净利拐头 右侧确认回测（T+1）===")
    print(
        f"{'变体':38s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s} {'持仓占比':>6s}"
    )
    for mode, label, col in variants:
        full, oos, hold = _run(mode, panel, sig, col)
        print(
            f"{label:38s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
            f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {hold:6.1f}%"
        )


if __name__ == "__main__":
    main()
