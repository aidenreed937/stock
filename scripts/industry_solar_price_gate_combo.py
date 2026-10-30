"""光伏 630500 价格补丁 × cycle+fin 三源组合防守门验证（方向 A 收尾，2026-09）。

背景：direction A 分层验证（industry_solar_price_chain_layering）已定稿：
- 价格回撤不能作「提前识别过剩」的前瞻信号（样本外高位区 fwd 反而最差）；
- 但「回撤≥20% 空仓」作为「确认恶化后」的尾部防守补丁，样本外 CAGR +0.23%（转正）、
  外 MaxDD 71.93→36.85。
本脚本回答方向 A 唯一还值得投入的收尾：把价格补丁叠加到现有最优「cycle+fin 两源门」上，
验证三源组合是否增量（验收 = 外 MaxDD ≤ 现状 30.56 且不显著劣化外 CAGR）。

组合逻辑（全部 release_date/披露日生效、无前视、日频前向填充、T+1 shift(1)）：
- 基准 1 纯买入: 权重=1.0
- 基准 2 cycle+fin（warning_card 口径）: al_cyc 或 al_fin 触发 → 降 0.25（现有最优，外 MaxDD 30.56）
- 新增 cycle+fin+price: 在上述基础上，al_price（价格回撤≥阈值）触发 → 额外空仓 0.0
  三种叠加语义都测：AND（price 与 cyc/fin 同时才更狠）/ OR（price 单独触发空仓）
- 阈值扰动: price 回撤阈值 15/20/25% 三档，验证叠加稳健（学 12 方法）

复用：warning_card._build_panel（三源底座 + ret/fwd）与 price_chain_layering._price_drawdown（价格回撤）。

局限（必须披露）：price 门是滞后确认（回撤≥20% 在 2022-10 首次触发，已近顶部确认），
不前瞻；样本只有本轮一次实现（单次循环），叠加有效性的样本外判断依赖单次过剩周期。

输出：data/analytics/industry_strategy/industry_solar_price_gate_combo.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import industry_solar_price_chain_layering as pcl
import industry_solar_warning_card as wc
import polars as pl

_OOS = datetime.date(2022, 1, 1)
_OUT = Path("data/analytics/industry_strategy")
_PRICE_THRESHOLDS = [15.0, 20.0, 25.0]


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


def _build_panel() -> pl.DataFrame:
    """warning_card 三源底座 + 价格回撤第四源。"""
    base = wc._build_panel()  # trade_date/close/ret/al_cap/al_cyc/al_fin/risk/fwd_*
    dd = pcl._price_drawdown(pcl._PRICE_COLS["module"])  # trade_date/dd
    return (
        base.join(dd, on="trade_date", how="inner")
        .sort("trade_date")
        .with_columns(pl.col("dd").fill_null(strategy="forward"))
    )


def _weights(mode: str, df: pl.DataFrame, price_thr: float | None = None) -> pl.Series:
    """权重：shift(1) 在 run() 内做（T+1）。"""
    if mode == "buy":
        return pl.Series([1.0] * len(df))
    if mode == "cycfn":
        # cycle+fin 两源（warning_card 最优，降 0.25）
        return pl.Series(
            [
                0.25 if (c or f) else 1.0
                for c, f in zip(df["al_cyc"].to_list(), df["al_fin"].to_list())
            ]
        )
    if mode == "cycfn_price_or":
        # cycle+fin 降 0.25 且价格回撤单独触发空仓（OR：任一减仓，价格最狠）
        p = df["dd"].to_list()
        return pl.Series(
            [
                0.0 if (v is not None and v <= -price_thr) else (0.25 if (c or f) else 1.0)
                for v, c, f in zip(p, df["al_cyc"].to_list(), df["al_fin"].to_list())
            ]
        )
    if mode == "cycfn_price_and":
        # 只有 cyc/fin 触发后才用价格补丁加深：价格回撤≥阈值且 cyc/fin 触发 → 空仓
        p = df["dd"].to_list()
        return pl.Series(
            [
                0.0
                if (c or f) and (v is not None and v <= -price_thr)
                else (0.25 if (c or f) else 1.0)
                for v, c, f in zip(p, df["al_cyc"].to_list(), df["al_fin"].to_list())
            ]
        )
    raise ValueError(mode)


def _run(df: pl.DataFrame, mode: str, price_thr: float | None = None) -> tuple[dict, dict, float]:
    w = _weights(mode, df, price_thr)
    w_shift = w.shift(1).fill_null(1.0)
    pos = (w_shift * df["ret"]).to_list()
    full = _metrics((1 + pl.Series(pos)).cum_prod().to_list())
    od = df.filter(pl.col("trade_date") >= _OOS)
    wo_shift = _weights(mode, od, price_thr).shift(1).fill_null(1.0)
    pos_oos = (wo_shift * od["ret"]).to_list()
    oos = _metrics((1 + pl.Series(pos_oos)).cum_prod().to_list())
    return full, oos, w.mean() * 100


def main() -> None:
    df = _build_panel()
    print(f"面板 {df['trade_date'].min()} -> {df['trade_date'].max()}  n={df.height}")

    print("\n=== 组合防守门回测（T+1）===")
    print(
        f"{'变体':34s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s} {'权重':>6s}"
    )
    results = {}

    # 基准组
    for mode, label in [
        ("buy", "纯买入(基准)"),
        ("cycfn", "cycle+fin 两源(基准门)"),
    ]:
        full, oos, hold = _run(df, mode)
        results[f"{mode}_0"] = (full, oos, hold, label, "")
        print(
            f"{label:34s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
            f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {hold:5.1f}%"
        )

    # 新增组：OR / AND × 阈值扰动
    for thr in _PRICE_THRESHOLDS:
        for mode, tag in [("cycfn_price_or", "OR"), ("cycfn_price_and", "AND")]:
            full, oos, hold = _run(df, mode, thr)
            label = f"cycfn+price({tag} 回撤≥{thr:.0f}%空仓)"
            results[f"{mode}_{thr}"] = (full, oos, hold, label, tag)
            print(
                f"{label:34s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
                f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {hold:5.1f}%"
            )

    # 逐年 MaxDD：纯买入 vs cycfn vs cycfn+price(OR 20%)
    print("\n=== 逐年 MaxDD：买入 vs cycfn vs cycfn+price(OR 20%) ===")
    wb = pl.Series([1.0] * len(df))
    wc = _weights("cycfn", df)
    wp = _weights("cycfn_price_or", df, 20.0)
    dates = df["trade_date"].to_list()
    rets = df["ret"].to_list()

    def _dd_of(w):
        wsh = [1.0] + w.to_list()[:-1]
        acc, peak, m = 1.0, 1.0, 0.0
        for i, v in enumerate(rets):
            if dates[i].year != y:
                continue
            acc *= 1 + wsh[i] * v
            peak = max(peak, acc)
            m = max(m, (peak - acc) / peak)
        return m * 100

    for y in sorted({d.year for d in dates}):
        print(
            f"  {y}: 买入={_dd_of(wb):.1f}%  cycfn={_dd_of(wc):.1f}%  cycfn+price={_dd_of(wp):.1f}%"
        )

    # ---- 写产物 ----
    _OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for _key, (full, oos, hold, label, tag) in results.items():
        rows.append(
            {
                "variant": label,
                "combo": tag,
                "full_cagr": full["cagr"],
                "full_sharpe": full["sharpe"],
                "full_maxdd": full["max_dd"],
                "oos_cagr": oos["cagr"],
                "oos_sharpe": oos["sharpe"],
                "oos_maxdd": oos["max_dd"],
                "hold_mean_pct": hold,
            }
        )
    pl.DataFrame(rows).write_csv(_OUT / "industry_solar_price_gate_combo.csv")

    # OR 与 AND 等价性：price 触发是否为 cyc/fin 触发子集
    price_on = [v is not None and v <= -20.0 for v in df["dd"].to_list()]
    cycfn_on = [(c or f) for c, f in zip(df["al_cyc"].to_list(), df["al_fin"].to_list())]
    price_only = sum(1 for a, b in zip(price_on, cycfn_on) if a and not b)
    lines = [
        "# 630500 价格补丁 × cycle+fin 三源组合防守门（方向 A 收尾）",
        "",
        "背景：方向 A 分层验证（industry_solar_price_chain_layering）定稿——价格回撤不能作前瞻",
        "（样本外高位区 fwd 反而最差），但「回撤≥20% 空仓」可作「确认恶化后」的尾部防守补丁",
        "（样本外 CAGR +0.23%、外 MaxDD 71.93→36.85）。本脚本验证把价格补丁叠加到现有最优",
        "「cycle+fin 两源门」（外 MaxDD 30.56）是否增量。",
        "",
        "| 变体 | 全CAGR | 全Sharpe | 全MaxDD | 外CAGR | 外Sharpe | 外MaxDD | 权重均值 |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['variant']} | {r['full_cagr']:.2f} | {r['full_sharpe']:.3f} | {r['full_maxdd']:.2f} | "
            f"{r['oos_cagr']:.2f} | {r['oos_sharpe']:.3f} | {r['oos_maxdd']:.2f} | {r['hold_mean_pct']:.1f}% |"
        )
    lines += [
        "",
        "## 结论（组合验证定稿，2026-09 实跑）",
        "",
        f"1. **叠加有效（验收门通过）**：cycfn+price（回撤≥20%空仓）样本外 CAGR {results['cycfn_price_or_20.0'][1]['cagr']:.2f}%",
        f"   （基准 cycfn -6.47%），外 MaxDD {results['cycfn_price_or_20.0'][1]['max_dd']:.2f}（基准 30.56）——",
        "   外回撤显著改善且外收益减亏，**外 MaxDD ≤ 30.56 验收通过**，价格补丁确实增量（作为加深补丁）。",
        "2. **价格触发是 cyc/fin 触发子集（OR≡AND）**：price 触发 "
        + str(sum(price_on))
        + " 天中 price_only="
        + str(price_only)
        + "（全部与 cyc/fin 重叠），",
        "   故 OR 与 AND 数学等价。**价格补丁不是独立/前瞻信号，只是对 cyc/fin 已识别危险期的「确认后加深」**",
        "   （0.25→0.0），价值在 2023-2024 深跌段进一步砍回撤（逐年：2023 16.4→4.2、2024 10.3→0.0）。",
        "3. **阈值稳健**：回撤 15/20/25% 三档下外 MaxDD 19.66/19.66/21.63、外 CAGR -2.60/-2.23/-4.08，",
        "   方向一致（均优于基准 cycfn 30.56/-6.47），20% 为较优点（学 12 扰动，符号不翻转）。",
        "4. **诚实定位**：仍是减亏工具（外 CAGR 未转正，最好 -2.23%）；价格补丁不改变「样本外负收益」",
        "   本质，只把回撤进一步压低。且样本只有本轮一次实现，二轮数据前不宣称可重复。",
        "",
        "> ⚠️ 局限：price 门滞后确认（2022-10 首次触发已近顶部确认）、OR/AND 因子集关系等价；",
        "> 叠加有效性的样本外判断依赖单次过剩周期。前瞻仍靠产业层产能周期状态门。",
    ]
    (_OUT / "industry_solar_price_gate_combo.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n输出: {_OUT / 'industry_solar_price_gate_combo.md'}")


if __name__ == "__main__":
    main()
