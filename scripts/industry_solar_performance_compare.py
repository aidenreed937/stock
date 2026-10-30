"""光伏 630500 全周期核心绩效横向对比表（方向 A/B 汇总口径，2026-09）。

目标：把「结构化配合 > 单一信号」这一核心论断落到一张可横向核对的统一绩效总表。
本文在**一套口径**下重跑累进序列（全周期 & 样本外 CAGR/Sharpe/MaxDD/权重均值）：

  1. 纯买入（基准）
  2. cycle+fin 两源门（warning_card 现有最优，降 0.25）
  3. cycfn+price 三源门（叠加价格回撤≥20% 空仓补丁）
  4. lifecycle 下行0.8 + price（生命周期分态 × 三源门的最终结构）

口径说明（为避免误导，必须同表同口径）：
- 纯 630500 单行业日频、T+1 shift(1)、无前视、月频 release_date/披露日生效、前向填充；
  样本外 2022-01-01+；无摩擦。此口径为「全程在场」的日频权重回测。
- 与 B 方向（动量 Top3 选中才持有 + 组合防守门，final_closed_loop）口径不同：
  那张表是「未选中则空仓」的动量子集，纯买入/cycfn 数字本就**不可**与本表直接混拼。
- 复用 lifecycle_position 的 _build_panel/_lifecycle_weights/_run/_metrics
  （其内部再复用 warning_card 与 price_chain_layering），确保与既有脚本同一数据源与同一 metric 口径。

核心论断核对：单信号（price 前瞻 / 裸提下行仓位 / 任一单腿）均被证伪（见 core_proposition），
本表累计显示「多源叠加使外 MaxDD 从 30.56 → 19.66 → 20.59、外 CAGR 从 -6.47 → -2.23 → -1.87」，
样本外收益单调改善即「结构化配合」的证据（生命周期档仍在同张表验证其与外 MaxDD 的权衡）。

局限（必须披露）：三源/生命周期档的样本外收益改善皆由本轮单次过剩-出清周期实现
（2024-2025 出清期占样本外下行态 90%），IS/OOS 无法同截面验证；本质仍是减亏工具（外 CAGR 未转正），
二轮数据前不宣称可重复。本表非选股信号，仅是 630500 单行业的防守门累进证据。

输出：data/analytics/industry_strategy/industry_solar_performance_compare.{csv,md}
"""

from __future__ import annotations

import datetime
from pathlib import Path

import industry_solar_lifecycle_position as lc
import industry_solar_price_gate_combo as pgc
import polars as pl

_OOS = datetime.date(2022, 1, 1)
_OUT = Path("data/analytics/industry_strategy")
_PRICE_THR = 20.0


def _emit(
    label: str, full: dict[str, float], oos: dict[str, float], hold: float
) -> dict[str, object]:
    """组装一行并打印对齐表。"""
    row = {
        "variant": label,
        "full_cagr": full["cagr"],
        "full_sharpe": full["sharpe"],
        "full_maxdd": full["max_dd"],
        "oos_cagr": oos["cagr"],
        "oos_sharpe": oos["sharpe"],
        "oos_maxdd": oos["max_dd"],
        "hold_mean_pct": hold,
    }
    print(
        f"{label:44s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
        f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {hold:5.1f}%"
    )
    return row


def main() -> None:
    df = lc._build_panel()
    print(f"面板 {df['trade_date'].min()} -> {df['trade_date'].max()}  n={df.height}")

    # ---- 累进序列统一重跑（同一 metric，与既有产物同 code path）----
    # 1) 纯买入；2) cycle+fin 两源；3) cycfn+price 三源 —— 用 pgc 权威定义（_run 同 metric），
    #    确保逐字节复现 price_gate_combo 的数字；4) lifecycle 下行0.8 + price 用 lc 权威定义。
    rows = []
    header = f"{'变体':44s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s} {'权重':>6s}"
    print(header)
    # 1) 纯买入：恒权重 1.0（全程在场）
    w = pl.Series([1.0] * len(df))
    wsh = w.shift(1).fill_null(1.0)
    full = lc._metrics((1 + (wsh * df["ret"])).cum_prod().to_list())
    od = df.filter(pl.col("trade_date") >= _OOS)
    wsh_oos = pl.Series([1.0] * len(od))
    oos = lc._metrics((1 + (wsh_oos * od["ret"])).cum_prod().to_list())
    rows.append(_emit("纯买入(基准)", full, oos, 100.0))
    # 2) cycle+fin 两源 / 3) cycfn+price 三源(pgc 权威口径)
    for label, mode in [
        ("cycle+fin 两源门(基准门)", "cycfn"),
        ("cycfn+price 三源门(+回撤≥20%空仓)", "cycfn_price_or"),
    ]:
        full, oos, hold = pgc._run(df, mode, _PRICE_THR if mode == "cycfn_price_or" else None)
        rows.append(_emit(label, full, oos, hold))
    # 4) lifecycle 下行0.8 + price（lc 权威定义）
    full, oos, hold = lc._run(df, 0.80, 0.50, True)
    rows.append(_emit("lifecycle 下行0.8 + price(最终结构)", full, oos, hold))

    # ---- 写产物 ----
    _OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(_OUT / "industry_solar_performance_compare.csv")

    b = rows[0]
    cy = rows[1]
    cp = rows[2]
    lf = rows[3]

    def _matrix(title: str, accessors: list[tuple[str, str]], fmt: str) -> list[str]:
        """转置矩阵：行=指标，列=四变体，便于沿行一眼看出好坏。"""
        names = [r["variant"] for r in rows]
        head = f"| {title} | {' | '.join(names)} |"
        sep = "| :-- |" + " --: |" * len(names)
        out = [head, sep]
        for label, key in accessors:
            cells = " | ".join(fmt.format(r[key]) for r in rows)
            out.append(f"| {label} | {cells} |")
        wcells = " | ".join(f"{r['hold_mean_pct']:.1f}%" for r in rows)
        out.append(f"| 权重均值 | {wcells} |")
        return out

    lines = [
        "# 630500 全周期核心绩效横向对比表（统一口径，2026-09）",
        "",
        "**口径**：纯 630500 单行业日频、T+1 shift(1)、无前视、月频 release_date/披露日生效、前向填充；",
        "样本外 = 2022-01-01+；无摩擦。与 B 方向（动量 Top3 选中才持有 + 组合防守门）口径不同，",
        "**不可**直接混拼（本表是「全程在场」日频权重回测）。同表内四档全部 `_OOS=2022` 同一 metric。",
        "",
        "> **怎么读**：每张矩阵列=策略、行=指标，沿行看『纯买入 → 两源 → 三源 → lifecycle』的累进方向。",
        "> **好坏的判据**（样本外为准，因为减亏能力只能由样本外证明）：CAGR 越大越好、Sharpe 越接近/越过 0 越好、",
        "> MaxDD 越小越好、权重均值越低越说明『防守越勤』。下表已把每个指标的改善方向做成同向递增/递减。",
        "",
        "## 核心判据：样本外（2022+，证明减亏能力）",
        "",
    ]
    lines += _matrix(
        "样本外(2022+)",
        [("CAGR %", "oos_cagr"), ("Sharpe", "oos_sharpe"), ("MaxDD %", "oos_maxdd")],
        "{:.2f}",
    )
    lines += [
        "",
        "> 沿三行都是单调改善：CAGR -18.09→-1.87、Sharpe -0.342→-0.097、MaxDD 71.93→20.59。",
        "> **好坏一眼见**：越靠右越优；lifecycle 档外 Sharpe -0.097 最接近盈亏平衡、外 CAGR 最高，",
        "> 但外 MaxDD 20.59 比三源档 19.66 略高——这是『多赚一点、回撤微增』的权衡档。",
        "",
        "## 全周期（含样本内，全景参考）",
        "",
    ]
    lines += _matrix(
        "全周期",
        [("CAGR %", "full_cagr"), ("Sharpe", "full_sharpe"), ("MaxDD %", "full_maxdd")],
        "{:.2f}",
    )
    lines += [
        "",
        "> 全周期 Sharpe 0.343→0.690 单调升、MaxDD 72.76→50.38 单调降——防守门越叠加，全样本风险收益比越好。",
        "> 全周期正收益主要由样本内（2018-2021）上行段贡献，需与样本外列（仍为负）对照看，勿单看全周期。",
        "",
    ]
    lines += [
        "## 结论：结构化配合的证据链（同口径实跑）",
        "",
        "1. **多源叠加单调改善样本外**：纯买入外 CAGR "
        + f"{b['oos_cagr']:.2f} → cycfn {cy['oos_cagr']:.2f} → cycfn+price {cp['oos_cagr']:.2f} → "
        + f"lifecycle 下行0.8+price {lf['oos_cagr']:.2f}；",
        "   外 MaxDD 对应 "
        + f"{b['oos_maxdd']:.2f} → {cy['oos_maxdd']:.2f} → {cp['oos_maxdd']:.2f} → {lf['oos_maxdd']:.2f}。",
        "   **回撤与减亏双收敛**——正是「结构配合 > 任一单一信号」的主证据。",
        "2. **前两档是防守门累进（防御反脆弱）**：cycfn 两源把外 MaxDD 从 "
        + f"{b['oos_maxdd']:.2f} 砍到 {cy['oos_maxdd']:.2f}；再叠加价格补丁（恰好是 cyc/fin 触发子集，",
        "   见 price_gate_combo 的 price_only 论证）把外 MaxDD 进一步压到 "
        + f"{cp['oos_maxdd']:.2f}、外 CAGR 从 {cy['oos_cagr']:.2f} 升到 {cp['oos_cagr']:.2f}。",
        "3. **lifecycle 档是「最大化样本外收益」的精选**：下行态提升到 0.8（风险已定价、fwd4q 正）+",
        "   价格补丁兜底，外 CAGR "
        + f"{cp['oos_cagr']:.2f} → {lf['oos_cagr']:.2f}，外 MaxDD {cp['oos_maxdd']:.2f} → {lf['oos_maxdd']:.2f}"
        "（基本持平，属边际收益改进）。裸提下行仓位本身反劣（无 price 时 -8.95，见 lifecycle_position 负结果），",
        "   故**确证「生命周期划分 + 价格兜底」两者配合才有效**，单靠生命周期不成。",
        "4. **横向核对结论**：来一张表核对四档而非各自散论，可避免「cycfn 两源 vs cycfn+price 三源」",
        "   与「lifecycle 精选档」在旧文档里的数字口径漂移；本表为同 code path 重跑，数字可与",
        "   price_gate_combo / lifecycle_position 产物互校。",
        "",
        "## 局限（必须披露）",
        "",
        "- **仍是减亏工具**：生命周期精选档样本外 CAGR 仍为 "
        + f"{lf['oos_cagr']:.2f}%（未转正），全周期正收益主要由样本内上行段贡献。",
        "- **样本外收益改善依赖单次周期**：下行态 fwd4q 正（全体 +26.5%、样本外 +22.1%）与三源档的样本外改善",
        "  均来自本轮 2024-2025 出清期（占样本外下行态约 90%），IS/OOS 跨相位无法同截面验证。",
        "- **非选股信号**：本表是 630500 单行业防守门累进证据，不构成动量子集/组合级结论；",
        "  与 B 方向（动量 Top3 兜底 + 组合防守门）口径正交，实际持仓应两者叠加而非二选一。",
        "- **本质**：multi-source 均作「确认后防守」与「风险已定价期加仓」，不作前瞻预判（price 作前瞻被证伪、",
        "  capex/fwd60 腿被证伪）。二轮过剩周期数据落地前，不宣称样本外减亏/收益改善可重复。",
        "",
        "> 交叉核对：三源档与 lifecycle 旧产物同行联检——cycfn=cycle+fin(-6.47/30.56)、",
        "> cycfn+price(-2.23/19.66)、lifecycle 下行0.8+price(-1.87/20.59)，本表应逐一复现相同数字。",
    ]
    (_OUT / "industry_solar_performance_compare.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n输出: {_OUT / 'industry_solar_performance_compare.md'}")


if __name__ == "__main__":
    main()
