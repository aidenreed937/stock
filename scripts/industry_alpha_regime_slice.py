"""中观行业轮动 alpha 的市场状态切片诊断。

回答归因验证中的核心问题：中观策略 vs 中证全指的超额，是「信号全废」还是
「只在极端市里被 beta 淹没」。用宏观风控 v5 的状态机定义「常态期」（v5 不动作的
区间）与「极端期」，分别统计四个中观策略相对全指的日均超额、胜率与区间累计超额。

状态定义（对齐 ``MacroRotationV5Strategy.on_bar`` 的动作条件）：
- 常态期：panic <= 65 且 overheat <= 65 且 全指 20 日乖离 <= 15%（v5 不动作）；
- 极端期：其余（含恐慌 panic>65、过热 overheat>65、极端乖离 bias>15%）。

数据：``data/analytics/industry_strategy/multi_strategy_nav.csv`` 的净值 +
``data/analytics/macro_risk/latest/risk_factors.parquet`` 的 panic/overheat。
全指 bias20 由「中证全指」净值算（nav 是 close 的线性缩放，乖离不变）。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

_BENCH = "中证全指"
_STRATEGIES = (
    "industry_momentum",
    "industry_reversal",
    "industry_scissors",
    "industry_meta_router",
)
_PANIC_ENTRY = 65.0
_OVERHEAT = 65.0
_BIAS_MAX = 0.15
_MA_WINDOW = 20


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= window:
            acc -= values[i - window]
        if i >= window - 1:
            out.append(acc / window)
        else:
            out.append(None)
    return out


def _metrics(daily_excess: list[float]) -> dict[str, float]:
    """日均超额、胜率、区间累计超额。"""
    n = len(daily_excess)
    if n == 0:
        return {"mean_excess": 0.0, "win_rate": 0.0, "cum_excess": 0.0, "days": 0}
    mean_ex = sum(daily_excess) / n * 100.0
    win = sum(1 for x in daily_excess if x > 0) / n * 100.0
    cum = 1.0
    for x in daily_excess:
        cum *= 1.0 + x
    cum_ex = (cum - 1.0) * 100.0
    return {"mean_excess": mean_ex, "win_rate": win, "cum_excess": cum_ex, "days": n}


def main() -> None:
    root = Path("data/analytics")
    industry_path = root / "industry_strategy" / "multi_strategy_nav.csv"
    risk_path = root / "macro_risk" / "latest" / "risk_factors.parquet"
    out_dir = root / "industry_strategy"
    out_dir.mkdir(parents=True, exist_ok=True)

    nav_df = (
        pl.read_csv(industry_path).select(["trade_date", _BENCH, *_STRATEGIES]).sort("trade_date")
    )
    risk_df = (
        pl.read_parquet(risk_path)
        .select(["trade_date", "panic_index", "overheat_index"])
        .with_columns(pl.col("trade_date").cast(pl.Utf8))
        .sort("trade_date")
    )
    df = nav_df.join(risk_df, on="trade_date", how="inner").sort("trade_date")

    dates = df["trade_date"].to_list()
    bench_nav = df[_BENCH].to_list()
    panic = df["panic_index"].to_list()
    overheat = df["overheat_index"].to_list()

    # 全指 20 日乖离（用净值等价计算）
    ma20 = _rolling_mean(bench_nav, _MA_WINDOW)
    bias = [
        (bench_nav[i] / ma20[i] - 1.0) if ma20[i] is not None else 0.0
        for i in range(len(bench_nav))
    ]

    strat_navs = {c: df[c].to_list() for c in _STRATEGIES}
    strat_rets = {
        c: [v[i] / v[i - 1] - 1.0 for i in range(1, len(v))] for c, v in strat_navs.items()
    }
    bench_rets = [bench_nav[i] / bench_nav[i - 1] - 1.0 for i in range(1, len(bench_nav))]

    # 标记状态（按优先级：极端乖离 > 恐慌 > 过热 > 常态）
    regimes: list[str] = []
    for i in range(1, len(dates)):
        p = panic[i]
        o = overheat[i]
        b = bias[i]
        if p <= 75.0 and b > _BIAS_MAX:
            regimes.append("extreme_bias")
        elif p > _PANIC_ENTRY:
            regimes.append("panic")
        elif o > _OVERHEAT:
            regimes.append("overheat")
        else:
            regimes.append("normal")
    # regimes 与 strat_rets/bench_rets 逐日对齐（收益日 = 1..n-1）

    # 分组统计
    rows: list[dict] = []
    for regime in ("normal", "panic", "overheat", "extreme_bias"):
        idx = [i for i, r in enumerate(regimes) if r == regime]
        if not idx:
            continue
        bench_reg = [bench_rets[i] for i in idx]
        for c in _STRATEGIES:
            ex = [strat_rets[c][i] - bench_rets[i] for i in idx]
            m = _metrics(ex)
            rows.append(
                {
                    "regime": regime,
                    "strategy": c,
                    "days": m["days"],
                    "mean_excess_bp": round(m["mean_excess"] * 100.0, 1),  # 日均超额(基点)
                    "win_rate": round(m["win_rate"], 1),
                    "cum_excess": round(m["cum_excess"], 2),
                }
            )
        # 基准行
        rows.append(
            {
                "regime": regime,
                "strategy": _BENCH,
                "days": len(bench_reg),
                "mean_excess_bp": None,
                "win_rate": None,
                "cum_excess": None,
            }
        )

    result = pl.DataFrame(rows)
    csv_path = out_dir / "industry_alpha_regime_slice.csv"
    result.write_csv(csv_path)

    # 打印
    print("=== 中观策略 vs 中证全指：分市场状态超额 ===")
    print(result)

    # 常态期天数占比
    total = len(regimes)
    normal_days = sum(1 for r in regimes if r == "normal")
    print(f"\n常态期天数占比: {normal_days}/{total} = {normal_days / total:.1%}")

    # 关键结论：常态期是否所有策略都无正超额
    normal = result.filter(pl.col("regime") == "normal").filter(pl.col("strategy") != _BENCH)
    any_positive = normal.filter(pl.col("mean_excess_bp") > 0).height
    best = normal.sort("mean_excess_bp", descending=True).to_dicts()[0] if normal.height else None

    md_lines = [
        "# 中观行业轮动 alpha 市场状态切片诊断",
        "",
        "> 回答：中观策略 vs 中证全指的超额，是「信号全废」还是「只在极端市被 beta 淹没」。",
        "> 状态定义对齐 `MacroRotationV5Strategy`：常态期 = panic<=65 且 overheat<=65 且 全指20日乖离<=15%。",
        "",
        "| 状态 | 策略 | 天数 | 日均超额(bp) | 日胜率 | 区间累计超额 |",
        "| :--- | :--- | :---: | :---: | :---: | :---: |",
    ]
    for r in result.to_dicts():
        ex = f"{r['mean_excess_bp']:+.1f}" if r["mean_excess_bp"] is not None else "-"
        wr = f"{r['win_rate']:.1f}%" if r["win_rate"] is not None else "-"
        cu = f"{r['cum_excess']:+.2f}%" if r["cum_excess"] is not None else "-"
        md_lines.append(f"| {r['regime']} | {r['strategy']} | {r['days']} | {ex} | {wr} | {cu} |")

    verdict = (
        f"常态期 {best['strategy']} 日均超额 {best['mean_excess_bp']:+.1f}bp"
        if best
        else "无常态期数据"
    )
    md_lines += [
        "",
        "## 结论",
        "",
        f"常态期天数占比 {normal_days / total:.1%}；常态期最优中观策略为 {verdict}。",
        f"常态期 {any_positive}/{normal.height} 个策略日均超额为正。",
        "",
        f"明细 CSV: `{csv_path.name}`",
        "",
    ]
    md_path = out_dir / "industry_alpha_regime_slice.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\n诊断留档: {md_path}")
    print(f"明细 CSV: {csv_path}")


if __name__ == "__main__":
    main()
