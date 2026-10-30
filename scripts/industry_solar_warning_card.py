"""光伏 630500 三源预警卡（季度/拐点层复合预警）.

问题（photovoltaic/10 待办）：是否在季度/拐点层复用「需求分位贴顶」信号，叠加到
产能周期状态 + 财报 TTM 之上，构成"贴顶分位 + 产能周期 + 财报 TTM 三源预警卡"。

三源（全部 release_date/披露日生效、无前视、日频前向填充、T+1）：
1. 贴顶 cap : 光伏装机 3mma YoY 36 月分位 >= 80（industry_solar_cap_defense 口径，贴顶反身）。
2. 产能 cycle: 产业层产能周期状态 ∈ {过剩, 下行}（industry_solar_cycle_position 危险/过渡区）。
3. 财报 fin : 成分股聚合净利 TTM 同比 < 0（industry_solar_profit_turn_ext 的 pos 门，认定恶化）。

复合卡：risk = 激活源个数 (0..3) -> 预警档位（绿/黄/橙/红），映射防守权重。

核心检验（回答 §9 待办）：
- 三源各自独立区分度（单源 alert vs 反事实 fwd2q/4q）；
- 三源两两/三方重叠（是否冗余，贴顶是否带来增量信息）；
- 复合预警档位 fwd2q/4q 是否单调（预警越多越空越负）；
- 复合卡防守门回测（T+1）vs 纯买入 vs "仅 cycle+fin（不含贴顶）"，
  ——回答"贴顶在季尺度是否增量于 (cycle+fin)"。全周期 + 样本外 2022+。

局限：规则阈值取自既有研究（贴顶 80、状态分档、fin<0），非本脚本反向拟合；
预警卡明确是「防守减仓」语义，不宣称择时转正（framework: 财报层仅滞后验证、
产业层状态门为季度尺度唯一前瞻信号）。

输出：data/analytics/industry_strategy/industry_solar_warning_card.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import industry_solar_cap_defense as cap
import industry_solar_cycle_position as cyc
import industry_solar_profit_turn_ext as pte
import polars as pl

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_CAP_THR = 80  # 贴顶分位阈值（cap_defense 口径）
_CYCLE_ALERTS = {"过剩", "下行"}  # 状态门危险/过渡区
_FWD = {"2q": 126, "4q": 252}
_MAP = Path("scripts/industry_direction_map.py")
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "630500"


def _cap_series() -> pl.DataFrame:
    """贴顶分位：solar_capacity monthly_new_capacity_3mma -> _monthly_pct -> pct(日频)."""
    df = pl.read_parquet("data/curated/industry/solar_capacity.parquet").select(
        ["trade_date", "release_date", "monthly_new_capacity_3mma"]
    )
    leg = cap._monthly_pct(df, "monthly_new_capacity_3mma", window_months=36)
    return leg.select(["trade_date", "pct"]).rename({"pct": "cap_pct"})


def _cycle_series() -> pl.DataFrame:
    """产能周期状态（release_date 生效，日频唯一保留）。"""
    states = cyc._build_states()
    return states.select(["release_date", "state"]).rename({"release_date": "trade_date"})


def _fin_series() -> pl.DataFrame:
    """财报 TTM 同比 pos 门（净利<0 认定恶化），披露日生效，日频。"""
    sig = pte._signal()  # trade_date, turn, pos, up
    return sig.select(["trade_date", "pos"])


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
    """合并三源就绪信号到日频网格（无前视、T+1 在权重层 shift(1)）。"""
    cap_s = _cap_series()
    cyc_s = _cycle_series()
    fin_s = _fin_series()

    panel = (
        pl.read_parquet(_PANEL)
        .filter((pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START))
        .select(["trade_date", "close"])
        .sort("trade_date")
        .join(cap_s, on="trade_date", how="left")
        .join(cyc_s, on="trade_date", how="left")
        .join(fin_s, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(
            pl.col("cap_pct").fill_null(strategy="forward"),
            pl.col("state").fill_null(strategy="forward"),
            pl.col("pos").fill_null(strategy="forward"),
        )
        .with_columns(
            pl.col("close").pct_change().fill_null(0.0).alias("ret"),
            pl.col("cap_pct").fill_null(0.0),
            pl.col("pos").fill_null(0.0),
        )
        .with_columns(
            (pl.col("cap_pct") >= _CAP_THR).fill_null(False).alias("al_cap"),
            pl.col("state").is_in(_CYCLE_ALERTS).fill_null(False).alias("al_cyc"),
            (pl.col("pos") < 0.5).fill_null(False).alias("al_fin"),  # pos=0 净利<0
        )
        .with_columns(
            (
                pl.col("al_cap").cast(pl.Int32)
                + pl.col("al_cyc").cast(pl.Int32)
                + pl.col("al_fin").cast(pl.Int32)
            ).alias("risk")
        )
    )
    for w in _FWD.values():
        panel = panel.with_columns(
            (pl.col("close").shift(-w) / pl.col("close") - 1).alias(f"fwd_{w}_ret")
        )
    return panel


def _dist(df: pl.DataFrame, label: str) -> None:
    if len(df) < 20:
        print(f"    {label}: n<20 跳过")
        return
    cells = []
    for lbl, w in _FWD.items():
        v = df[f"fwd_{w}_ret"].drop_nulls()
        if len(v) < 10:
            cells.append(f"{lbl}: n<10")
            continue
        vals = v.to_list()
        mean = sum(vals) / len(vals) * 100
        med = sorted(vals)[len(vals) // 2] * 100
        up = sum(1 for x in vals if x > 0) / len(vals) * 100
        cells.append(f"{lbl} 均值{mean:6.1f}% 中位{med:6.1f}% 胜率{up:3.0f}%")
    print(f"    {label} (n={len(df)}): " + " | ".join(cells))


def _main() -> None:
    df = _build_panel()
    print("=== 三源预警卡 —— 季度尺度（fwd2q/4q）独立区分度 ===")
    print("单源 alert vs 反事实：")
    for col, name in [("al_cap", "贴顶cap"), ("al_cyc", "产能cycle"), ("al_fin", "财报fin")]:
        print(f"  {name}:")
        _dist(df.filter(pl.col(col)), "alert")
        _dist(df.filter(~pl.col(col)), "~alert")

    print("\n=== 三源两两重叠（是否冗余信息）===")
    rows = df.filter(pl.col("cap_pct").is_not_null())
    print(f"  总有效 {rows.height} 天")
    for combo in [
        ("al_cap", "al_cyc"),
        ("al_cap", "al_fin"),
        ("al_cyc", "al_fin"),
    ]:
        a, b = combo
        both = rows.filter(pl.col(a) & pl.col(b)).height
        onlya = rows.filter(pl.col(a) & ~pl.col(b)).height
        onlyb = rows.filter(~pl.col(a) & pl.col(b)).height
        print(
            f"  {a}×{b}: 双激活 {both} ({both / rows.height * 100:.1f}%) | 仅{a} {onlya} | 仅{b} {onlyb}"
        )

    print("\n=== 复合预警档位 risk=0..3 → fwd2q/4q 分布（单调性检验）===")
    for r in [0, 1, 2, 3]:
        _dist(df.filter(pl.col("risk") == r), f"risk={r}")

    # 卡表映射
    card = {0: 1.0, 1: 0.7, 2: 0.4, 3: 0.25}

    def weights(mode: str, dd: pl.DataFrame) -> pl.Series:
        if mode == "buy":
            return pl.Series([1.0] * len(dd))
        if mode == "card":  # 三源复合卡
            return pl.Series([card[r] for r in dd["risk"].to_list()])
        if mode == "cycfn":  # 仅 cycle+fin（不含贴顶）
            return pl.Series(
                [
                    0.25 if (c or f) else 1.0
                    for c, f in zip(dd["al_cyc"].to_list(), dd["al_fin"].to_list())
                ]
            )
        if mode == "cyc":  # 仅 cycle
            return pl.Series([0.25 if c else 1.0 for c in dd["al_cyc"].to_list()])
        if mode == "fin":  # 仅 fin
            return pl.Series([0.25 if f else 1.0 for f in dd["al_fin"].to_list()])
        return pl.Series([0.25 if ap else 1.0 for ap in dd["al_cap"].to_list()])  # 仅 cap

    def run(mode: str, dd: pl.DataFrame) -> tuple[dict, dict, float]:
        w_shift = weights(mode, dd).shift(1).fill_null(1.0)
        pos = (w_shift * dd["ret"]).to_list()
        full = _metrics((1 + pl.Series(pos)).cum_prod().to_list())
        od = dd.filter(pl.col("trade_date") >= _OOS)
        wo_shift = weights(mode, od).shift(1).fill_null(1.0)
        pos_oos = (wo_shift * od["ret"]).to_list()
        oos = _metrics((1 + pl.Series(pos_oos)).cum_prod().to_list())
        hold = weights(mode, dd).mean() * 100
        return full, oos, hold

    print("\n=== 复合卡防守门回测（T+1）vs 纯买入 vs 仅 cycle+fin ===")
    print(
        f"{'变体':32s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s} {'权重':>6s}"
    )
    results = {}
    for mode, label in [
        ("buy", "纯买入(基准)"),
        ("cap", "仅贴顶 cap 单源"),
        ("cyc", "仅 cycle 单源"),
        ("fin", "仅 fin 单源"),
        ("cycfn", "cycle+fin(不含贴顶)"),
        ("card", "三源复合卡(0.7/0.4/0.25)"),
    ]:
        full, oos, hold = run(mode, df)
        results[mode] = (full, oos, hold)
        print(
            f"{label:32s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
            f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {hold:5.1f}%"
        )

    # 逐年 MaxDD：买入 vs 三源卡（稳健性）
    print("\n=== 逐年 MaxDD：纯买入 vs 三源卡（全周期）===")
    _ = results["buy"]

    def dd(series: pl.Series) -> float:
        peak, m, acc = -1e9, 0.0, 1.0
        for v in series.to_list():
            acc *= 1 + (0.0 if v is None else v)
            peak = max(peak, acc)
            m = max(m, (peak - acc) / peak)
        return m * 100

    for y in sorted({d.year for d in df["trade_date"].to_list()}):
        wb = pl.Series([1.0] * len(df))
        wc = pl.Series([card[r] for r in df["risk"].to_list()])
        pb = (wb.shift(1).fill_null(1.0) * df["ret"]).filter(df["trade_date"].dt.year() == y)
        pc = (wc.shift(1).fill_null(1.0) * df["ret"]).filter(df["trade_date"].dt.year() == y)
        print(f"  {y}: 买入MaxDD={dd(pb):.1f}%  三源卡MaxDD={dd(pc):.1f}%")

    # 写入 csv + md
    out_rows = []
    for lbl, w in _FWD.items():
        for r in [0, 1, 2, 3]:
            sub = df.filter(pl.col("risk") == r)[f"fwd_{w}_ret"].drop_nulls().to_list()
            if len(sub) >= 10:
                out_rows.append(
                    {
                        "horizon": lbl,
                        "risk": r,
                        "n": len(sub),
                        "mean": sum(sub) / len(sub) * 100,
                        "median": sorted(sub)[len(sub) // 2] * 100,
                        "win": sum(1 for x in sub if x > 0) / len(sub) * 100,
                    }
                )
    _OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(out_rows).write_csv(_OUT / "industry_solar_warning_card.csv")

    # 回测变体指标（含 Sharpe）结构化导出
    bt_rows = []
    for mode, label in [
        ("buy", "纯买入(基准)"),
        ("cap", "仅贴顶 cap"),
        ("cyc", "仅 cycle"),
        ("fin", "仅 fin"),
        ("cycfn", "cycle+fin"),
        ("card", "三源复合卡"),
    ]:
        full, oos, hold = results[mode]
        bt_rows.append(
            {
                "mode": mode,
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
    pl.DataFrame(bt_rows).write_csv(_OUT / "industry_solar_warning_card_backtest.csv")

    def rank(label, m):
        return f"| {label} | {m['cagr']:.2f} | {m['sharpe']:.3f} | {m['max_dd']:.2f} | "

    lines = [
        "# 630500 三源预警卡（贴顶分位 + 产能周期 + 财报 TTM，季度尺度复合预警）",
        "",
        "问题：是否在季度/拐点层复用需求分位贴顶信号，叠加到产能周期状态 + 财报 TTM 之上。",
        "三源（release_date/披露日生效、无前视、日频前向填充、T+1）：",
        "- 贴顶 cap: 光伏装机 3mma YoY 36 月分位 >= 80（贴顶反身）。",
        "- 产能 cycle: 产业层产能周期状态 ∈ {过剩, 下行}（危险/过渡区）。",
        "- 财报 fin : 成分股聚合净利 TTM 同比 < 0（恶化认定）。",
        "复合卡: risk = 激活源个数 (0..3) -> 防守权重 {0:1.0, 1:0.7, 2:0.4, 3:0.25}。",
        "",
        "| 预警档位 | 天数 | fwd2q均值/中位/胜率 | fwd4q均值/中位/胜率 |",
        "| :-- | --: | --: | --: |",
    ]
    for r in [0, 1, 2, 3]:
        sub = df.filter(pl.col("risk") == r)
        cells = []
        for _lbl, w in _FWD.items():
            v = sub[f"fwd_{w}_ret"].drop_nulls().to_list()
            if len(v) < 10:
                cells.append("-")
            else:
                cells.append(
                    f"{sum(v) / len(v) * 100:.1f}%/{sorted(v)[len(v) // 2] * 100:.1f}%/{sum(1 for x in v if x > 0) / len(v) * 100:.0f}%"
                )
        name = {0: "绿(全绿)", 1: "黄(1源)", 2: "橙(2源)", 3: "红(3源)"}[r]
        lines.append(f"| {name} | {sub.height} | {cells[0]} | {cells[1]} |")
    lines += [
        "",
        "| 回测变体 | 全CAGR | 全Sharpe | 全MaxDD | 外CAGR | 外Sharpe | 外MaxDD | 权重均值 |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for lbl, m in [
        ("纯买入(基准)", "buy"),
        ("仅贴顶 cap", "cap"),
        ("仅 cycle", "cyc"),
        ("仅 fin", "fin"),
        ("cycle+fin", "cycfn"),
        ("三源复合卡", "card"),
    ]:
        full, oos, hold = results[m]
        lines.append(
            f"| {lbl} | {full['cagr']:.2f} | {full['sharpe']:.3f} | {full['max_dd']:.2f} | "
            f"{oos['cagr']:.2f} | {oos['sharpe']:.3f} | {oos['max_dd']:.2f} | {hold:.1f}% |"
        )
    lines += [
        "",
        "**结论（回答 §9 待办）**：",
        "- 贴顶 cap 单源不成立（全周期 -0.59%、最差单源）：贴顶在景气上行段也触发，其 fwd4q 均值仍",
        "  为正（28.0%），作为危险源降仓会砍掉真实上行暴露；样本外 -14.90% 也劣于纯买入。",
        "- 产能 cycle 是唯一强前瞻危险源（alert fwd4q -5.9%/38% vs ~alert 67.9%/81%），与框架重新定稿一致。",
        "- 财报 fin 是滞后信号（fin<0 的 fwd4q 均值 50.4%/91% 主要被 2019 利润谷底→2020-2021 景气",
        "  上行单一episode的均值回归拉高，属聚合假象，非可靠前瞻；2024-2026 的 fin<0 期 fwd 为负）。",
        "  它单源作防守弱（外 -16.58% 仅略好于买入），但在 cycle+fin 两源里通过更大幅降仓",
        "  （权重 54%）换来 MaxDD 双改善（全 50.38/外 30.56）。",
        "- 决定性对比：**加入贴顶会劣化防守**。cycle+fin 两源（全 13.06/外 -6.47/外MaxDD 30.56）",
        "  全面优于 三源复合卡（全 5.82/外 -12.84/外MaxDD 46.84）——贴顶在季度防守层不携带",
        "  正向增量，反而引入 2020-08 后上行段的错误降仓。",
        "- **§9 定稿：季度/拐点防守层不重用需求分位贴顶信号**；最优形态为「产业层产能周期状态 +",
        "  财报 TTM 两源防守门」。三源预警卡作废，贴顶仅保留 fwd60 失效层级的研究记录。",
        "- 局限: 阈值取自既有研究非本脚本反向拟合；防守减仓语义，不宣称择时转正（framework 定稿）。",
    ]
    (_OUT / "industry_solar_warning_card.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    _main()
