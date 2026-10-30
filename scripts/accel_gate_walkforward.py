"""G3 狂热放缓门 Walk-Forward 样本外稳健性检验。

承接 scripts/accel_regime_gate_experiment.py 的发现：G3（overheat≥T 且 20D 加速度≤0
时减仓）全周期 CAGR/MDD 均优于基准，但分年/分范式超额分布不均，需检验是否过拟合。

本脚本做「参数无拟合的滚动样本外稳健性检验」：
- 规则参数（阈值 T、加速度符号门）全部来自先验（双轨指数配置 60/65 + 先导探针），
  不存在训练拟合；因此滚动 OOS = 逐年/逐段用固定参数评估稳定性，而非参数重估 WFO；
- 阈值网格 55.0 ~ 70.0（步长 2.5，覆盖 warning 60 / critical 65 参考点），
  输出 阈值 × 年份 OOS 超额矩阵 + 稳健性统计（正超额年份占比 / 年均超额 / 最差单年）；
- 判定规则：正超额年份占比 ≥ 8/12 且年均超额 > 0.3pp → 稳健候选（建议正式化）；
  否则按「被否定 → 停用留档」惯例处理。

评估口径与实验脚本完全一致（T+1、摩擦 0.06% 单边、空仓=现金、基准 000985.CSI）。

用法:
    uv run python scripts/accel_gate_walkforward.py
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from accel_regime_gate_experiment import _attach_strat_ret, _backtest, _load_panel, _run_rule

THRESHOLDS = [55.0, 57.5, 60.0, 62.5, 65.0, 67.5, 70.0]
YEARS = list(range(2015, 2027))  # 与实验脚本范式窗口一致
OUT_PATH = Path("data/analytics/macro_strategy/robustness/accel_gate_walkforward.md")


def _year_ret(df: pl.DataFrame, yr: int) -> float | None:
    s = df.filter(pl.col("trade_date").dt.year() == yr)
    if s.height < 20:
        return None
    nav = 1.0
    for r in s["strat_ret"].to_list():
        nav *= 1.0 + r
    return nav - 1.0


def main() -> None:
    df = _load_panel()
    bench = _attach_strat_ret(df.with_columns(pl.lit(1.0).alias("pos")))
    bench_bt = _backtest(bench)

    # 各阈值全周期表现 + 逐年 OOS 超额
    rows: list[dict] = []
    for t in THRESHOLDS:
        rd = _attach_strat_ret(_run_rule(df, "overheat_index", t, "<="))
        bt = _backtest(rd)
        excess = {yr: (_year_ret(rd, yr), _year_ret(bench, yr)) for yr in YEARS}
        vals = []
        for yr in YEARS:
            r, b = excess[yr]
            vals.append(None if (r is None or b is None) else (r - b) * 100)
        pos_years = sum(1 for v in vals if v is not None and v > 0)
        usable = sum(1 for v in vals if v is not None)
        mean_ex = sum(v for v in vals if v is not None) / usable if usable else 0.0
        worst = min((v for v in vals if v is not None), default=0.0)
        rows.append(
            {
                "t": t,
                "bt": bt,
                "vals": vals,
                "pos_years": pos_years,
                "usable": usable,
                "mean_ex": mean_ex,
                "worst": worst,
            }
        )

    lines = [
        "# G3 狂热放缓门 Walk-Forward 样本外稳健性检验",
        "",
        "> 参数无拟合的滚动样本外检验：规则参数（阈值、a20≤0 符号门）全部来自先验，"
        "逐年用固定参数评估超额，检验跨期稳定性而非重估参数。口径同实验脚本（T+1、"
        f"摩擦 0.06% 单边、空仓=现金、基准 000985.CSI B&H 净值 {bench_bt['total']:.3f} / "
        f"CAGR {bench_bt['cagr'] * 100:+.2f}% / MDD {bench_bt['mdd'] * 100:.1f}%）。",
        "",
        "## 阈值网格全周期表现",
        "| 阈值 | 净值 | CAGR | 最大回撤 | 换仓次数 | 年均超额(pp) | 正超额年份 | 最差单年(pp) |",
        "| --: | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['t']:.1f} | {r['bt']['total']:.3f} | {r['bt']['cagr'] * 100:+.2f}% | "
            f"{r['bt']['mdd'] * 100:.1f}% | {r['bt']['switches']} | {r['mean_ex']:+.2f} | "
            f"{r['pos_years']}/{r['usable']} | {r['worst']:+.1f} |"
        )

    lines.append("\n## 分年 OOS 超额矩阵（G3 各阈值 − 基准，pp；+ 为正超额）")
    lines.append("| 年份 | " + " | ".join(f"{t:.1f}" for t in THRESHOLDS) + " |")
    lines.append("| :-- | " + " | ".join(["--:"] * len(THRESHOLDS)) + " |")
    for i, yr in enumerate(YEARS):
        cells = [str(yr)]
        for r in rows:
            v = r["vals"][i]
            cells.append("n/a" if v is None else f"{v:+.1f}")
        lines.append("| " + " | ".join(cells) + " |")

    # 稳健性判定：正超额年份占比 + 年均超额
    lines.append("\n## 稳健性判定")
    cands = [r for r in rows if r["pos_years"] >= 8 and r["mean_ex"] > 0.3]
    best = max(rows, key=lambda r: (r["pos_years"], r["mean_ex"]))
    lines.append(
        f"- 最优阈值: {best['t']:.1f}（正超额 {best['pos_years']}/{best['usable']} 年，"
        f"年均超额 {best['mean_ex']:+.2f}pp，最差单年 {best['worst']:+.1f}pp）"
    )
    if cands:
        picks = "、".join(f"{r['t']:.1f}" for r in cands)
        lines.append(
            f"- **稳健候选: {picks}** —— 跨期超额为正的年份占多数，建议走六步流水线正式化验证"
        )
    else:
        lines.append(
            "- **不稳定/过拟合嫌疑** —— 无阈值满足「正超额 ≥ 8/12 年 且 年均超额 > 0.3pp」，"
            "按「被否定 → 停用留档」惯例处理，不升级为策略"
        )
    lines.append(
        "\n> 注: 本检验为固定先验参数的跨期稳健性审计（非参数重估 WFO）；"
        "G3 的增益主要来自回撤防御（MDD 改善），超额集中在少数年份时即使均值>0 也不宜直接使用。"
    )
    out = "\n".join(lines)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
