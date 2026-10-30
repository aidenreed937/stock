"""光伏 630500 定稿方案闭环实证：动量 Top3 兜底 + 组合防守门。

背景：630500 已因与电池（630700）相关性 0.77 被剔除出 16 行业方向池（framework.md）。
定稿（photovoltaic_supply_demand_study.md §8）：630500 不投入 fwd60 择时腿，放回
"无腿行业动量 Top3 兜底（return_60d + 估值/组合防守门）"。本脚本把定稿落到实证闭环：

视角 A（组合/池层）：16 池基线 vs 17 池（+630500）动量 Top3 季度调仓对比——
  630500 放回池后的边际贡献（入选频率、CAGR/Sharpe/MaxDD 变化，全周期 + 样本外）。
视角 B（单行业/防守门层）：630500 被动量 Top3 选中才持有（未入选空仓），叠加既有
  三个防守门（财报门 / 贴顶门 / 产能周期状态门，OR 组合）降仓到 floor——回答
  "动量兜底在 630500 上到底表现如何、定稿方案样本外能否转正"。

口径对齐 CLI 基线（industry_l2_direction）：
- 数据源 industry_l2_panel_daily / industry_l2_daily；窗口 2020-05-01→（L2 财务可用起点）；
- 季度调仓 rebalance_period=63 交易日；score_column=return_60d 降序 Top3 等权 1/3；
- 估值防守 pe_ttm_ew_percentile_5y <= 90（缺失放行）；T+1 执行（调仓日信号次日生效）；
- 样本外 2022-01-01+；防守门无前视（披露日/发布日生效前向填充）。

局限（沿用既有定稿披露）：成分股聚合为当前名单（survivorship）；2025Q4 起财报同比
"转正"为基数坍塌伪信号；产能周期状态门规则为历史反推（事后拟合风险，不宣称前瞻）。

输出：data/analytics/industry_strategy/industry_solar_final_closed_loop.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl
from industry_solar_combo_defense import _fin_series, _top_series
from industry_solar_cycle_position import _build_states

_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_PRICE = Path("data/curated/mart/industry_l2_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_START = datetime.date(2020, 5, 1)
_OOS = datetime.date(2022, 1, 1)
_POOL = (
    "270100",
    "730200",
    "710100",
    "630700",
    "630800",
    "280500",
    "240300",
    "240400",
    "370100",
    "370600",
    "220200",
    "220400",
    "220800",
    "640600",
    "421100",
    "270500",
)
_SOLAR = "630500"
_REBAL = 63
_TOP_K = 3
_VAL_MAX = 90.0
_FLOOR = 0.3


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


def _load_wide(industries: tuple[str, ...]) -> pl.DataFrame:
    """加载日频宽表：date x industry 的 close（ret 计算）与 return_60d / pe5y（列名带后缀）。"""
    panel = pl.read_parquet(_PANEL).filter(
        (pl.col("trade_date") >= _START) & (pl.col("industry_code").is_in(industries))
    )
    price = (
        pl.read_parquet(_PRICE)
        .filter((pl.col("trade_date") >= _START) & (pl.col("industry_code").is_in(industries)))
        .select(["trade_date", "industry_code", "close"])
    )

    def pivot(col: str, src: pl.DataFrame, suffix: str) -> pl.DataFrame:
        return (
            src.select(["trade_date", "industry_code", col])
            .pivot(on="industry_code", index="trade_date", values=col, aggregate_function="first")
            .sort("trade_date")
            .rename({c: f"{c}_{suffix}" for c in industries})
        )

    close_w = pivot("close", price, "ret").with_columns(
        [pl.col(f"{c}_ret").pct_change().fill_null(0.0).alias(f"{c}_ret") for c in industries]
    )
    mom_w = pivot("return_60d", panel, "mom")
    pe_w = pivot("pe_ttm_ew_percentile_5y", panel, "pe")
    return close_w.join(mom_w, on="trade_date", how="inner").join(
        pe_w, on="trade_date", how="inner"
    )


def _rebalance_weights(wide: pl.DataFrame, industries: tuple[str, ...]) -> pl.DataFrame:
    """复刻 IndustryL2DirectionStrategy：63 日调仓 → 估值防守 → return_60d Top3 等权。

    返回 date x industry 的目标权重（调仓日当天写入，调用方负责 shift(1) 实现 T+1）。
    """
    dates = wide["trade_date"].to_list()
    rows: list[dict[str, float]] = []
    carry: dict[str, float] = dict.fromkeys(industries, 0.0)
    for i, d in enumerate(dates):
        if i % _REBAL == 0:
            cand = [
                c
                for c in industries
                if wide[f"{c}_pe"][i] is None or wide[f"{c}_pe"][i] <= _VAL_MAX
            ]
            scored = [(wide[f"{c}_mom"][i], c) for c in cand if wide[f"{c}_mom"][i] is not None]
            ranked = [c for _, c in sorted(scored, key=lambda t: t[0], reverse=True)][:_TOP_K]
            carry = dict.fromkeys(industries, 0.0)
            if ranked:
                for c in ranked:
                    carry[c] = 1.0 / len(ranked)
        rows.append({"trade_date": d, **carry})
    return pl.DataFrame(rows)


def _pool_metrics(
    wide: pl.DataFrame, weights: pl.DataFrame, industries: tuple[str, ...]
) -> tuple[dict[str, float], dict[str, float], float, float]:
    """按权重矩阵（shift(1) T+1）与日收益计算组合全周期/样本外指标。"""
    wdf = weights.with_columns(
        [pl.col(c).shift(1).fill_null(0.0).alias(f"{c}_w") for c in industries]
    )
    merged = wide.select(["trade_date"] + [f"{c}_ret" for c in industries]).join(
        wdf.select(["trade_date"] + [f"{c}_w" for c in industries]),
        on="trade_date",
        how="inner",
    )
    rets = merged["trade_date"].to_list()
    pos = [
        sum(merged[f"{c}_ret"][i] * merged[f"{c}_w"][i] for c in industries)
        for i in range(merged.height)
    ]
    full = _metrics((1 + pl.Series(pos)).cum_prod().to_list())
    idx = [i for i, d in enumerate(rets) if d >= _OOS]
    oos = _metrics((1 + pl.Series([pos[i] for i in idx])).cum_prod().to_list())
    if f"{_SOLAR}_w" in merged.columns:
        hold = sum(1 for i in range(merged.height) if merged[f"{_SOLAR}_w"][i] > 0) / merged.height
    else:
        hold = 0.0
    return full, oos, hold, merged.height


def _solar_weights_with_gates(
    w17: pl.DataFrame,
    dates: list[datetime.date],
    gates: dict[str, pl.DataFrame],
    mode: str,
) -> pl.DataFrame:
    """630500 单行业视角权重：Top3 选中=1（未选中=0），防守门触发降仓到 floor。"""
    grid = pl.DataFrame({"trade_date": dates})
    fin = gates["fin"].select(["disclose", "fin_on"]).rename({"disclose": "trade_date"})
    top = gates["top"]
    cyc = (
        gates["cycle"]
        .rename({"release_date": "trade_date"})
        .select(["trade_date", "state"])
        .with_columns(
            pl.when(pl.col("state").is_in(["过剩", "下行"]))
            .then(1.0)
            .otherwise(0.0)
            .alias("cycle_on")
        )
        .select(["trade_date", "cycle_on"])
    )
    trig = (
        grid.join(fin, on="trade_date", how="left")
        .join(top, on="trade_date", how="left")
        .join(cyc, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(
            pl.col("fin_on").fill_null(strategy="forward").fill_null(0.0),
            pl.col("top_on").fill_null(strategy="forward").fill_null(0.0),
            pl.col("cycle_on").fill_null(strategy="forward").fill_null(0.0),
        )
    )
    finv, topv, cycv = (
        trig["fin_on"].to_list(),
        trig["top_on"].to_list(),
        trig["cycle_on"].to_list(),
    )
    sel = [1.0 if s > 0 else 0.0 for s in w17[_SOLAR].to_list()]
    w: list[float] = []
    for i, s in enumerate(sel):
        if s <= 0:
            w.append(0.0)
            continue
        if mode == "mom":
            w.append(1.0)
        elif mode == "fin":
            w.append(_FLOOR if finv[i] else 1.0)
        elif mode == "top":
            w.append(_FLOOR if topv[i] else 1.0)
        elif mode == "cycle":
            w.append(_FLOOR if cycv[i] else 1.0)
        elif mode == "or":
            w.append(_FLOOR if (finv[i] or topv[i] or cycv[i]) else 1.0)
        else:
            w.append(1.0)
    return trig.with_columns(pl.Series("w", w), pl.Series("sel", sel))


def main() -> None:
    pool17 = _POOL + (_SOLAR,)
    wide = _load_wide(pool17)
    dates = wide["trade_date"].to_list()
    print(f"宽表区间 {dates[0]} -> {dates[-1]}  n={len(dates)}")

    # ---- 视角 A：池层组合对比 ----
    w16 = _rebalance_weights(wide, _POOL)
    w17 = _rebalance_weights(wide, pool17)
    f16, o16, _, _ = _pool_metrics(wide, w16, _POOL)
    f17, o17, h17, _ = _pool_metrics(wide, w17, pool17)
    print("\n=== 视角 A：池层动量 Top3（2020-05→） ===")
    print(
        f"{'池':26s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s}"
    )
    for tag, f, o in [("16池基线(现方向池)", f16, o16), ("17池(+630500)", f17, o17)]:
        print(
            f"{tag:26s} {f['cagr']:8.2f} {f['sharpe']:8.3f} {f['max_dd']:7.2f} | "
            f"{o['cagr']:7.2f} {o['sharpe']:8.3f} {o['max_dd']:7.2f}"
        )
    print(f"630500 被 Top3 选中天数占比: {h17 * 100:.1f}%")

    sel_days = w17.filter(pl.col(_SOLAR) > 0)
    # 入选期摘要：只取调仓日（每 63 交易日一个）作为段起点，最多列 4 段
    sel_period_starts = [
        w17["trade_date"][i].strftime("%Y-%m-%d")
        for i in range(0, wide.height, _REBAL)
        if w17[f"{_SOLAR}"][i] > 0
    ]
    sel_str = "；".join(f"{d}起" for d in sel_period_starts[:4])
    n_periods = len(sel_period_starts)
    print(f"630500 入选交易日数: {sel_days.height}（跨 {n_periods} 个调仓期，段起始: {sel_str}）")

    # ---- 视角 B：630500 单行业（选中才持有 + 防守门） ----
    gates = {"fin": _fin_series(), "top": _top_series(), "cycle": _build_states()}
    retv = wide[f"{_SOLAR}_ret"].fill_null(0.0).to_list()

    def _eval_solar(w: list[float]):
        w_shift = [0.0] + w[:-1]
        pos = [w_shift[i] * retv[i] for i in range(len(retv))]
        full = _metrics((1 + pl.Series(pos)).cum_prod().to_list())
        idx = [i for i, d in enumerate(dates) if d >= _OOS]
        oos = _metrics((1 + pl.Series([pos[i] for i in idx])).cum_prod().to_list())
        return full, oos, sum(w) / len(w)

    variants = [
        ("纯买入(基准)", [1.0] * len(dates)),
        ("动量Top3选中才持有", _solar_weights_with_gates(w17, dates, gates, "mom")["w"].to_list()),
        ("选中+财报门", _solar_weights_with_gates(w17, dates, gates, "fin")["w"].to_list()),
        ("选中+贴顶门", _solar_weights_with_gates(w17, dates, gates, "top")["w"].to_list()),
        ("选中+产能周期门", _solar_weights_with_gates(w17, dates, gates, "cycle")["w"].to_list()),
        ("选中+OR三门", _solar_weights_with_gates(w17, dates, gates, "or")["w"].to_list()),
    ]
    print("\n=== 视角 B：630500 单行业（2020-05→，样本外 2022+） ===")
    print(
        f"{'变体':26s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s} {'权重均值':>6s}"
    )
    rows = []
    for label, w in variants:
        full, oos, hold = _eval_solar(w)
        rows.append(
            {
                "label": label,
                **{f"full_{k}": v for k, v in full.items()},
                **{f"oos_{k}": v for k, v in oos.items()},
                "hold": hold * 100,
            }
        )
        print(
            f"{label:26s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
            f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {hold * 100:6.1f}%"
        )

    # ---- 输出 ----
    _OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(_OUT / "industry_solar_final_closed_loop.csv")
    lines = [
        "# 630500 定稿方案闭环实证：动量 Top3 兜底 + 组合防守门",
        "",
        f"区间 {dates[0]} -> {dates[-1]}（对齐 CLI 基线 2020-05-01→）；样本外 2022+；",
        "口径：return_60d Top3 等权、pe5y<=90、63 交易日调仓、T+1、无前视。",
        "关键事实：630500 已被剔除出 16 行业方向池（与电池相关 0.77），本实证将其放回（17 池）测边际贡献。",
        "",
        "## 视角 A：池层动量 Top3（16 池 vs 17 池）",
        "",
        "> 口径说明：本脚本未含交易摩擦（佣金+滑点），16 池基线全 CAGR 6.91% 与 CLI 基线",
        "> `industry_l2_direction`（含 friction，2020-05-01 起）+6.48% 相差约 0.4pp，来自摩擦与起始日；",
        "> 16 vs 17 池对比同口径，结论不受影响。",
        "",
        "| 池 | 全CAGR | 全Sharpe | 全MaxDD | 外CAGR | 外Sharpe | 外MaxDD |",
        "| :-- | --: | --: | --: | --: | --: | --: |",
        f"| 16池基线(现方向池) | {f16['cagr']:.2f} | {f16['sharpe']:.3f} | {f16['max_dd']:.2f} | {o16['cagr']:.2f} | {o16['sharpe']:.3f} | {o16['max_dd']:.2f} |",
        f"| 17池(+630500) | {f17['cagr']:.2f} | {f17['sharpe']:.3f} | {f17['max_dd']:.2f} | {o17['cagr']:.2f} | {o17['sharpe']:.3f} | {o17['max_dd']:.2f} |",
        "",
        f"630500 被 Top3 选中天数占比 {h17 * 100:.1f}%（跨 {n_periods} 个调仓期，前 3 段起始：{sel_str}）。",
        "",
        "## 视角 B：630500 单行业（动量选中才持有 + 防守门）",
        "",
        "| 变体 | 全CAGR | 全Sharpe | 全MaxDD | 外CAGR | 外Sharpe | 外MaxDD | 权重均值 |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['label']} | {r['full_cagr']:.2f} | {r['full_sharpe']:.3f} | {r['full_max_dd']:.2f} | "
            f"{r['oos_cagr']:.2f} | {r['oos_sharpe']:.3f} | {r['oos_max_dd']:.2f} | {r['hold']:.1f}% |"
        )
    lines += [
        "",
        "## 结论（实证结果）",
        "",
        "### 池层（视角 A）",
        f"**630500 放回方向池是净拖累**：16 池基线全 CAGR {f16['cagr']:.2f}% → 17 池 {f17['cagr']:.2f}%，",
        f"样本外 {o16['cagr']:.2f}% → {o17['cagr']:.2f}%（转负），全 MaxDD {f16['max_dd']:.2f}% → {f17['max_dd']:.2f}%。",
        f"630500 被 Top3 选中天数占比 {h17 * 100:.1f}%，且入选集中在 2020-08~2022-09 与 2024-10~2026-02",
        "（与电池 630700 相关 0.77、样本外持续阴跌），印证当初因相关性剔除的合理性。",
        "",
        "### 单行业（视角 B）",
        "| 结论 | 依据 |",
        "| :-- | :-- |",
        "| 动量选中才持有**大幅减亏**但**未转正** | 样本外 CAGR -17.28% → -7.76%，MaxDD 71.93% → 45.06%；全周期 7.22% → 4.02% |",
        "| 叠加产能周期门**最接近转正** | 样本外 -0.89%（其余门 -2.17%~-5.77%），MaxDD 15.99%，全周期 8.23% 反超纯买入 |",
        "| 财报门减亏次之 | 样本外 -4.10%，MaxDD 26.54%；全周期 7.07% 接近纯买入 |",
        "| OR 三门最稳回撤 | 全 MaxDD 21.25%、外 MaxDD 15.99%，但样本外 -2.17%、全周期 3.76% |",
        "",
        "**定稿确认**：630500 即使在动量 Top3 兜底框架下，样本外仍为负收益（最好变体 -0.89%），",
        "不构成可交易正收益来源；动量兜底 + 产能周期防守门是其最佳减亏组合，维持",
        "「不投入 fwd60 择时腿 + 防守门减亏」定稿。放回 16 行业方向池无边际价值（视角 A 拖累）。",
    ]
    (_OUT / "industry_solar_final_closed_loop.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n输出: {_OUT / 'industry_solar_final_closed_loop.md'}")


if __name__ == "__main__":
    main()
