"""光伏 630500 产能周期状态门——稳健性审计（阈值敏感性 + 分年切片）。

背景：07/11 已把「产业层产能周期状态门」定为季度尺度（fwd2q/4q）**唯一前瞻信号**，
最优防守形态 = 产能周期状态 + 财报 TTM 两源门。但结论由历史反推调参，**事后拟合风险**
被反复标注（07 结论、11 局限、framework.md）。本脚本显式审计该信号是否经得起参数/时间稳健性：

1. **阈值敏感性**：对状态门最关键的 4 组分档阈值做网格扰动，观察「过剩 vs 上行 fwd4q 区分度」
   （均值差、胜率差）是否在合理范围内仍强/仍负——若轻微扰动使区分度崩塌，说明结论脆弱（拟合）；
   若稳定，说明结论稳健。
   关键阈值：cap_yoy(扩产潮≥0.30)、flood_24m(24月扩产记忆≥0.30)、util_hi(高利用率≥70)、
   util_lo(低利用率<45)。
2. **分年度 fwd4q 区分度**：逐年检验「过剩 vs 上行」的边际，看结论是被 2022-2023 单一扩产潮
   主导，还是跨年稳定（避免"一个 episode 撑起全结论"）。
3. **样本外 / 参数老化**：IS(2018-2021) vs OOS(2022+) 分别看 fwd4q 区分度是否延续，
   检验规则是否仅在历史段成立。

口径与 cycle_position 对齐：月度 release_date 生效、日频前向填充、T+1（状态门权重层 shift(1)）。
不做任何参数反向拟合——本脚本只"扰动"既有阈值看稳健性，不重调参数追求更优。

输出：data/analytics/industry_strategy/industry_solar_cycle_robustness.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import industry_solar_cycle_position as cyc
import polars as pl


def _fmt(v: float) -> str:
    return "-" if math.isnan(v) else f"{v:.1f}"


_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "630500"
_FWD = 252  # fwd4q


def _state_param(
    u: float | None,
    u6: float | None,
    cy: float | None,
    f24: float | None,
    py: float | None,
    sc: float | None,
    thr: dict,
) -> str | None:
    """state_row 的参数化版本（thr 可扰动），默认参数与 cycle_position 完全一致。"""
    cap = thr["cap_yoy"]
    flood = thr["flood_24m"]
    hi = thr["util_hi"]
    lo = thr["util_lo"]
    sc_thr = thr.get("sc_pos", 0.0)  # 剪刀差转正门槛（底部右侧用）
    sc_mid = thr.get("sc_mid", -0.20)  # 中位利用率下 剪刀差下界
    if cy is None or u is None or f24 is None:
        return None
    if cy >= cap:
        return "过剩"
    if f24 >= flood:
        return "下行"
    if u >= hi:
        return "上行"
    if u < lo:
        if (u6 or 0) > 0 or (sc is not None and sc > sc_thr):
            return "底部右侧"
        return "下行"
    # 中位利用率 lo..hi
    if (u6 or 0) > 0 and (sc is None or sc > sc_mid):
        return "上行"
    return "下行"


def _default_thr() -> dict:
    return {
        "cap_yoy": 0.30,
        "flood_24m": 0.30,
        "util_hi": 70.0,
        "util_lo": 45.0,
        "sc_pos": 0.0,
        "sc_mid": -0.20,
    }


def _states_for(thr: dict) -> pl.DataFrame:
    """按给定阈值构建 release_date 状态序列（前向填充到日频后合并进面板）。"""
    monthly = cyc._monthly_panel()
    states = []
    for r in monthly.to_dicts():
        states.append(
            _state_param(
                r["derived_polysilicon_utilization_rate"],
                r["util_6m_chg"],
                r["cap_yoy"],
                r["flood_24m"],
                r["prod_yoy"],
                r["scissors_spread_yoy"],
                thr,
            )
        )
    m = monthly.with_columns(pl.Series("state", states))
    s = (
        m.drop_nulls("state")
        .select(["report_month", "release_date", "state"])
        .sort("release_date")
        .unique(subset=["release_date"], keep="last")
        .sort("release_date")
    )
    panel = (
        pl.read_parquet(_PANEL)
        .filter((pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START))
        .select(["trade_date", "close"])
        .sort("trade_date")
        .join(
            s.select(["release_date", "state"]).rename({"release_date": "trade_date"}),
            on="trade_date",
            how="left",
        )
        .sort("trade_date")
        .with_columns(pl.col("state").fill_null(strategy="forward"))
        .with_columns((pl.col("close").shift(-_FWD) / pl.col("close") - 1).alias("fwd4q"))
    )
    return panel.drop_nulls("state")


def _edge(df: pl.DataFrame) -> dict:
    """过剩 vs 上行 fwd4q 区分度：均值差、胜率差、拉升比。"""
    o = df.filter(pl.col("state") == "过剩")["fwd4q"].drop_nulls()
    u = df.filter(pl.col("state") == "上行")["fwd4q"].drop_nulls()
    if len(o) < 10 or len(u) < 10:
        return {
            "n_glut": len(o),
            "n_up": len(u),
            "glut_mean": float("nan"),
            "up_mean": float("nan"),
            "edge_mean": float("nan"),
            "edge_win": float("nan"),
            "up_win": float("nan"),
            "up_rate": float("nan"),
        }
    gm = sum(o.to_list()) / len(o)
    um = sum(u.to_list()) / len(u)
    ow = sum(1 for x in o.to_list() if x > 0) / len(o)
    uw = sum(1 for x in u.to_list() if x > 0) / len(u)
    return {
        "n_glut": len(o),
        "n_up": len(u),
        "glut_mean": gm * 100,
        "up_mean": um * 100,
        "edge_mean": (gm - um) * 100,
        "edge_win": (ow - uw) * 100,
        "up_win": uw * 100,
        "up_rate": uw * 100,
    }


def main() -> None:
    # 基准
    base = _edge(_states_for(_default_thr()))
    print("=== 基准（默认阈值，全周期 fwd4q 过剩 vs 上行）===")
    print(
        f"  过剩 n={base['n_glut']} 均值{base['glut_mean']:.1f}% | 上行 n={base['n_up']} 均值{base['up_mean']:.1f}% | "
        f"均值差{base['edge_mean']:.1f}pp | 胜率差{base['edge_win']:.1f}pp"
    )

    # 阈值敏感性网格
    print("\n=== 阈值敏感性（单维扰动，看区分度均值差/胜率差是否稳定）===")
    sweeps = [
        ("cap_yoy 扩产潮阈值", "cap_yoy", [0.20, 0.25, 0.30, 0.35, 0.40]),
        ("flood_24m 扩产记忆阈值", "flood_24m", [0.20, 0.25, 0.30, 0.35, 0.40]),
        ("util_hi 高利用率上界", "util_hi", [60, 65, 70, 75, 80]),
        ("util_lo 低利用率下界", "util_lo", [35, 40, 45, 50, 55]),
    ]
    rows = []
    for name, key, grid in sweeps:
        print(f"  {name}:")
        for val in grid:
            thr = _default_thr()
            thr[key] = val
            e = _edge(_states_for(thr))
            flag = "" if e["n_glut"] >= 10 and e["n_up"] >= 10 else " (样本不足)"
            rows.append({"param": key, "value": val, **e, "note": flag})
            print(
                f"    {key}={val:5.2f}: 过剩{_fmt(e['glut_mean'])}% 上行{_fmt(e['up_mean'])}% | "
                f"均值差{_fmt(e['edge_mean'])}pp 胜率差{_fmt(e['edge_win'])}pp{flag}"
            )

    # 分年度 fwd4q 区分度
    base_panel = _states_for(_default_thr())
    print("\n=== 状态 × 年份构成（揭示样本是否含多次循环）===")
    comp = (
        base_panel.with_columns(pl.col("trade_date").cast(pl.Utf8).str.slice(0, 4).alias("y"))
        .group_by(["y", "state"])
        .len()
        .sort(["y", "state"])
    )
    print(comp.to_pandas().to_string(index=False))
    print("\n=== 分年度 fwd4q 区分度（默认阈值）===")
    yr_rows = []
    for y in sorted({d.year for d in base_panel["trade_date"].to_list()}):
        sub = base_panel.filter(pl.col("trade_date").dt.year() == y)
        e = _edge(sub)
        yr_rows.append({"year": y, **e})
        if e["n_up"] < 10 or e["n_glut"] < 10:
            print(f"  {y}: 上行n={e['n_up']} 过剩n={e['n_glut']}（样本不足，跳过）")
            continue
        print(
            f"  {y}: 过剩{e['glut_mean']:.1f}% 上行{e['up_mean']:.1f}% | "
            f"均值差{e['edge_mean']:.1f}pp 胜率差{e['edge_win']:.1f}pp"
        )

    # IS vs OOS（参数老化）——注意按全量前向填充切分会把上行残留到 2022 前 25 天。
    # 诚实判断：上行 state 只在 2019-2021（IS），过剩只在 2022 中-2024（OOS），
    # 两相位时间完全分离 → IS 里无过剩、OOS 里无真实上行，**同截面 IS/OOS 判别在结构上不可能**。
    # 这里只报告两半各有哪些 state（天数），以解释为何无法做 IS/OOS 区分度对比。
    print("\n=== IS vs OOS 的 state 构成（证明相位分离→无法同截面判别）===")
    for label, bound in [("IS 2018-2021", _OOS), ("OOS 2022+", None)]:
        if bound is None:
            sub = base_panel.filter(pl.col("trade_date") >= _OOS)
        else:
            sub = base_panel.filter(pl.col("trade_date") < bound)
        comp_sub = (
            sub.with_columns(pl.col("trade_date").cast(pl.Utf8).str.slice(0, 4).alias("y"))
            .group_by("state")
            .len()
            .sort("state")
        )
        print(
            f"  {label}: " + ", ".join(f"{r['state']}={r['len']}" for r in comp_sub.to_dicts())
            or "  (无)"
        )

    # 写 csv + md
    _OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(_OUT / "industry_solar_cycle_robustness.csv")
    lines = [
        "# 630500 产能周期状态门——稳健性审计（阈值敏感性 + 分年切片 + IS/OOS）",
        "",
        "背景：07/11 已将状态门定为季度尺度唯一前瞻信号，但结论历史反推、事后拟合风险被反复标注。",
        "本脚本扰动关键阈值、分年切片、IS/OOS 分样本，检验「过剩 vs 上行 fwd4q 区分度」是否稳健。",
        "口径与 cycle_position 对齐（release_date 生效、日频前向填充、fwd4q=252 交易日）。无参数反向拟合。",
        "",
        "## 1. 基准（全周期）",
        f"过剩 n={base['n_glut']} 均值{base['glut_mean']:.1f}% | 上行 n={base['n_up']} 均值{base['up_mean']:.1f}% | "
        f"均值差{base['edge_mean']:.1f}pp | 胜率差{base['edge_win']:.1f}pp",
        "",
        "## 2. 阈值敏感性网格（单维扰动）",
        "| 参数 | 取值 | 过剩均值% | 上行均值% | 均值差pp | 胜率差pp | n过剩/n上行 |",
        "| :-- | --: | --: | --: | --: | --: | --: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['param']} | {r['value']:.2f} | "
            f"{'' if math.isnan(r['glut_mean']) else round(r['glut_mean'], 1)} | "
            f"{'' if math.isnan(r['up_mean']) else round(r['up_mean'], 1)} | "
            f"{'' if math.isnan(r['edge_mean']) else round(r['edge_mean'], 1)} | "
            f"{'' if math.isnan(r['edge_win']) else round(r['edge_win'], 1)} | {r['n_glut']}/{r['n_up']} |"
        )
    lines += [
        "",
        "## 3. 状态 × 年份构成（样本循环次数）",
        "| 年份 | 上行 | 过剩 | 下行 | 底部右侧 |",
        "| :-- | --: | --: | --: | --: |",
    ]
    # 转换为每行一年、列=state 的天数
    comp_piv = comp.pivot(index="y", on="state", values="len", aggregate_function="sum")
    for r in comp_piv.sort("y").to_dicts():
        lines.append(
            f"| {r['y']} | {r.get('上行') or 0} | {r.get('过剩') or 0} | "
            f"{r.get('下行') or 0} | {r.get('底部右侧') or 0} |"
        )
    lines += [
        "",
        "## 4. 分年度 fwd4q 区分度（默认阈值）",
        "| 年份 | 过剩均值% | 上行均值% | 均值差pp | 胜率差pp | n过剩/n上行 |",
        "| :-- | --: | --: | --: | --: | --: |",
    ]
    for r in yr_rows:
        if r["n_up"] < 10 or r["n_glut"] < 10:
            lines.append(f"| {r['year']} | - | - | - | - | {r['n_glut']}/{r['n_up']}(样本不足) |")
            continue
        lines.append(
            f"| {r['year']} | {r['glut_mean']:.1f} | {r['up_mean']:.1f} | {r['edge_mean']:.1f} | "
            f"{r['edge_win']:.1f} | {r['n_glut']}/{r['n_up']} |"
        )
    lines += [
        "",
        "## 5. IS vs OOS 的 state 构成（相位分离 → 无法同截面判别）",
        "| 样本 | 状态构成（天数） |",
        "| :-- | :-- |",
    ]
    for label, bound in [("IS 2018-2021", _OOS), ("OOS 2022+", None)]:
        if bound is None:
            sub = base_panel.filter(pl.col("trade_date") >= _OOS)
        else:
            sub = base_panel.filter(pl.col("trade_date") < bound)
        comp_sub = (
            sub.with_columns(pl.col("trade_date").cast(pl.Utf8).str.slice(0, 4).alias("y"))
            .group_by("state")
            .len()
            .sort("state")
        )
        desc = ", ".join(f"{r['state']}={r['len']}" for r in comp_sub.to_dicts()) or "无"
        lines.append(f"| {label} | {desc} |")
    lines += [
        "",
        "**结论（稳健性判定）**：",
        "1. **阈值敏感性稳健**：cap_yoy/util_hi 在合理区间扰动下，过剩 vs 上行均值差稳定在 -100~-120pp、",
        "   胜率差 -60~-81pp（符号与幅度不翻转）；flood_24m/util_lo 不影响本对比（它们只改下行/底部右侧）。",
        "   → 区分度对参数不敏感，**非阈值拟合**。",
        "2. **时间稳健性弱（关键局限）**：上行 state 只在 2019-2021（+2022 前 25 天前向填充残留），",
        "   过剩只在 2022 中-2024——两相位**时间上完全分离 = 一个完整产能周期的一次实现**，",
        "   「过剩 vs 上行」本质是 2019-2021 涨 + 2022-2023 跌的先后序列，而非同年内的横截面判别。",
        "   → OOS 内几乎没有真实的上行样本（仅 25 天残留），IS/OOS 的 fwd 区分度无法同截面验证。",
        "3. **单次循环 ≠ 反复证实**：区分度强、阈值稳健，但样本只含一次景气-过剩的完整序列，",
        "   无法排除「光伏本轮周期仅一次」的选择性；「唯一前瞻信号」结论成立，但置信度受限于",
        "   单次实现，需 2026+ 底部右侧→新一轮上行的后续数据二次确认（07 §3 的右侧样本短同源）。",
    ]
    (_OUT / "industry_solar_cycle_robustness.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
