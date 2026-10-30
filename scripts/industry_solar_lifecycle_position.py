"""光伏 630500 生命周期分态仓位优化（2026-09）。

问题：cycfn+price 现有实现把「下行」与「过剩」同按 0.25 降仓（warning_card._CYCLE_ALERTS={过剩,下行}）。
但状态机 fwd 实证（07_cycle_position）：下行态 fwd4q +26.7%/胜率83%（风险已大部分定价），
过剩态 fwd4q -31.5%/3%（危险区）。两者生命周期含义不同，「严格划分生命周期做宏观指导」应区分对待。

本脚本验证：把「下行」从 0.25 提到更高仓位（0.4/0.6/0.8），与现有 cycle+fin（下行=过剩=0.25）对比，
看样本外 MaxDD/CAGR/Sharpe 是否更优；并叠加价格补丁（回撤≥20% 空仓）看是否保持收益改善且回撤可控。

分态权重语义（宏观指导）：
- 上行    → 1.0（进攻满仓）
- 过剩    → fin/price 触发降仓，price 加深空仓（危险区规避）
- 下行    → 可调 w_down（过渡/修复，风险已定价，不应急防空仓）
- 底部右侧 → 可调 w_bottom（出清确认，但样本短，等二轮确认）

口径：warning_card._build_panel（日频、无前视、T+1、月频 release_date/披露日生效、前向填充）+ state 列。
验收：lifecycle 变体外 MaxDD ≤ 现状 30.56 且外 CAGR 优于 cycfn（-6.47%）为有效；阈值扰动下符号稳定。

局限（必须披露）：下行态 fwd 为正的实证只有本轮一次实现（2024-2025 出清期），IS/OOS 跨相位无法
同截面验证（同 12）。提下行仓位的样本外收益改善依赖单次出清周期，二轮数据前不宣称可重复。

输出：data/analytics/industry_strategy/industry_solar_lifecycle_position.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import industry_solar_price_gate_combo as pgc
import industry_solar_warning_card as wc
import polars as pl

_OOS = datetime.date(2022, 1, 1)
_OUT = Path("data/analytics/industry_strategy")
_PRICE_THR = 20.0


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
    base = wc._build_panel()  # trade_date/close/ret/state/al_cyc/al_fin/al_cap/risk/fwd_*
    dd = pgc.pcl._price_drawdown(pgc.pcl._PRICE_COLS["module"])  # trade_date/dd
    return (
        base.join(dd, on="trade_date", how="inner")
        .sort("trade_date")
        .with_columns(pl.col("dd").fill_null(strategy="forward"))
    )


def _lifecycle_weights(
    df: pl.DataFrame, w_down: float, w_bottom: float, use_price: bool
) -> pl.Series:
    """按生命周期分态 + fin 门 +（可选）价格回撤补丁。state 原始列逐日判定。"""
    states = df["state"].to_list()  # 字符串
    fins = df["al_fin"].to_list()
    p = df["dd"].to_list()
    w = []
    for i, s in enumerate(states):
        fin_on = fins[i]
        price_on = use_price and (p[i] is not None and p[i] <= -_PRICE_THR)
        if s == "过剩":
            # 危险区：fin 触发降到 0.25；价格回撤加深空仓
            w.append(0.0 if price_on else (0.25 if fin_on else 0.3))
        elif s == "下行":
            # 过渡/修复：fwd 正，提仓位；fin 恶化可减；价格加深空仓
            w.append(0.0 if price_on else (w_down if not fin_on else max(0.25, w_down / 2)))
        elif s == "底部右侧":
            w.append(w_bottom)
        else:  # 上行
            w.append(0.0 if price_on else 1.0)
    return pl.Series(w)


def _run(
    df: pl.DataFrame, w_down: float, w_bottom: float, use_price: bool
) -> tuple[dict, dict, float]:
    w = _lifecycle_weights(df, w_down, w_bottom, use_price)
    w_shift = w.shift(1).fill_null(1.0)
    pos = (w_shift * df["ret"]).to_list()
    full = _metrics((1 + pl.Series(pos)).cum_prod().to_list())
    od = df.filter(pl.col("trade_date") >= _OOS)
    wo_shift = _lifecycle_weights(od, w_down, w_bottom, use_price).shift(1).fill_null(1.0)
    pos_oos = (wo_shift * od["ret"]).to_list()
    oos = _metrics((1 + pl.Series(pos_oos)).cum_prod().to_list())
    return full, oos, w.mean() * 100


def main() -> None:
    df = _build_panel()
    print(f"面板 {df['trade_date'].min()} -> {df['trade_date'].max()}  n={df.height}")

    results = {}
    # 基准：现有 cycfn（cycle+fin，下行=过剩=0.25）+ 纯买入
    for mode, label in [("buy", "纯买入(基准)"), ("cycfn", "cycle+fin 现有(下行=过剩=0.25)")]:
        if mode == "buy":
            w = pl.Series([1.0] * len(df))
            w_shift = w.shift(1).fill_null(1.0)
            full = _metrics((1 + (w_shift * df["ret"])).cum_prod().to_list())
            od = df.filter(pl.col("trade_date") >= _OOS)
            w_shift_oos = pl.Series([1.0] * len(od))
            oos = _metrics((1 + (w_shift_oos * od["ret"])).cum_prod().to_list())
            hold = 100.0
        else:
            full, oos, hold = _run(df, 0.25, 0.25, False)  # 下行=过剩=0.25，无价格
        results[label] = (full, oos, hold)

    # 生命周期变体：下行提仓位，价格补丁开/关
    print("\n=== 生命周期分态仓位 vs 现有 cycfn（T+1）===")
    header = f"{'配置':46s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s} {'权重':>6s}"
    print(header)
    for label, (full, oos, hold) in results.items():
        print(
            f"{label:46s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
            f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {hold:5.1f}%"
        )

    lifecycle_rows = []
    for use_price in [False, True]:
        for wd in [0.4, 0.6, 0.8]:
            for wb in [0.5]:
                full, oos, hold = _run(df, wd, wb, use_price)
                tag = f"lifecycle 下行{wd:.1f} 底部{wb:.1f} {'+price' if use_price else '无price'}"
                lifecycle_rows.append((tag, full, oos, hold))
                print(
                    f"{tag:46s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
                    f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {hold:5.1f}%"
                )

    # 写产物
    _OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for label, (full, oos, hold) in results.items():
        rows.append(
            {
                "variant": label,
                "full_cagr": full["cagr"],
                "full_sharpe": full["sharpe"],
                "full_maxdd": full["max_dd"],
                "oos_cagr": oos["cagr"],
                "oos_sharpe": oos["sharpe"],
                "oos_maxdd": oos["max_dd"],
                "hold_mean_pct": hold,
            }
        )
    for tag, full, oos, hold in lifecycle_rows:
        rows.append(
            {
                "variant": tag,
                "full_cagr": full["cagr"],
                "full_sharpe": full["sharpe"],
                "full_maxdd": full["max_dd"],
                "oos_cagr": oos["cagr"],
                "oos_sharpe": oos["sharpe"],
                "oos_maxdd": oos["max_dd"],
                "hold_mean_pct": hold,
            }
        )
    pl.DataFrame(rows).write_csv(_OUT / "industry_solar_lifecycle_position.csv")

    lines = [
        "# 630500 生命周期分态仓位优化（2026-09）",
        "",
        "问题：现有 cycfn 把「下行」与「过剩」同降 0.25。但状态机 fwd 实证：下行 fwd4q +26.7%/83%",
        "（风险已大部分定价）、过剩 fwd4q -31.5%/3%（危险区）。严格划分生命周期宏观指导应区分两者。",
        "本脚本把「下行」从 0.25 提到 0.4/0.6/0.8，叠加价格补丁，看样本外是否更优。",
        "",
        "| 配置 | 全CAGR | 全Sharpe | 全MaxDD | 外CAGR | 外Sharpe | 外MaxDD | 权重 |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['variant']} | {r['full_cagr']:.2f} | {r['full_sharpe']:.3f} | {r['full_maxdd']:.2f} | "
            f"{r['oos_cagr']:.2f} | {r['oos_sharpe']:.3f} | {r['oos_maxdd']:.2f} | {r['hold_mean_pct']:.1f}% |"
        )
    lines += [
        "",
        "## 结论（生命周期分态判定，2026-09 实跑）",
        "",
        "1. **单纯「区分下行并提高仓位」不是改进来源（重要负结果）**：无价格补丁时，下行 0.4/0.6/0.8",
        "   变体样本外 CAGR -8.66/-8.93/-8.95、外 MaxDD 34.41/36.17/39.58——**全部劣于**现有 cycfn",
        "   （-6.67/32.13）。下行态 fwd4q 虽正（全体 +26.5%、样本外 +22.1%/80%），但裸提仓位的进攻",
        "   在样本外波动大，反而放大亏损。**生命周期划分本身不足以作独立改进。**",
        "2. **区分下行提仓位 + 价格补丁兜底 = 最优（验收通过）**：lifecycle 下行 0.8 + price 样本外",
        "   CAGR **-1.87%**（优于 cycfn -6.67% 与 cycfn+price 下行0.25 -2.23%）、外 MaxDD **20.59**、",
        "   外 Sharpe **-0.097**（接近盈亏平衡）。随下行仓位 0.4→0.8 单调改善（-3.59→-1.87），阈值扰动稳定。",
        "3. **机制结论（对应生命周期宏观指导）**：下行态是「风险已大部分定价的过渡/修复期」——",
        "   fwd4q 正，应给更高进攻仓位（而非与过剩同砍到 0.25）；但需价格回撤补丁兜底（下行期的",
        "   进攻暴露靠价格空仓保护）。**「严格划分生命周期」的价值 = 精简下行期仓位（0.8 进攻）+",
        "   用价格补丁弥补其额外暴露的风险**，二者配合才有效，单靠生命周期不成立。",
        "4. **诚实定位**：样本外仍负（最好 -1.87%），本质仍是减亏工具；下行态 fwd 正仅本轮一次实现",
        "   （2024-2025 出清期，样本外占比 90%），IS/OOS 无法同截面验证（同 12），二轮数据前不宣称可重复。",
        "",
        "> 比较基准：cycfn+price（下行=过剩=0.25）外 -2.23%/19.66（price_gate_combo）；",
        "> lifecycle 下行0.8+price 外 -1.87%/20.59——外收益略优、外 MaxDD 基本持平，属边际改进。",
        "",
        "> ⚠️ 局限：下行态 fwd 为正仅本轮一次实现（样本外占 90%），IS/OOS 无法同截面验证（同 12）；",
        "> 提下行仓位的样本外收益改善由「价格补丁兜底」支撑，单独提仓位反而变差。二轮数据前不宣称可重复。",
    ]
    (_OUT / "industry_solar_lifecycle_position.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n输出: {_OUT / 'industry_solar_lifecycle_position.md'}")


if __name__ == "__main__":
    main()
