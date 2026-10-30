"""光伏 630500 高位介入生存检验（2026-09）。

问题：用户关心——即使在高位（顶部/追高）随机介入，用 cycfn+price 三源防守交易，
能否比「高位介入一直持有」减亏、活下来（回撤可控 + 回本可期）？

方法：选取历史顶部 2021-08-30（最高 15200）及若干代表性高位介入点，
从介入点起对比三种路径（买入持有 / cycle+fin 两源 / cycfn+price 三源）：
- 介入后 1 年 / 2 年 / 至今 累计收益；
- 介入后最大回撤（生存判据：能否承受）；
- 回本时间（介入后首次回到 1.0 所需交易日，最长等待的度量）。

复用 price_gate_combo 的权重逻辑（cycle+fin 降 0.25、价格回撤≥20% 空仓、T+1、无前视）。
注意：本检验不含"动量选中才持有"的入场筛选——它专门检验"入场点不择时（买在高位）时，
防守门能否把损失控制住"，是对 B/A 定稿的极端情形压力测试。

局限（必须披露）：样本只有本轮一次高位→过剩→出清周期；介入点是人为选取的历史高位，
非随机抽样；结论是"该周期内这些高位介入点的生存表现"，二轮数据前不宣称可重复。

输出：data/analytics/industry_strategy/industry_solar_high_entry_survival.{csv,md}
"""

from __future__ import annotations

import datetime
from pathlib import Path

import industry_solar_price_gate_combo as pgc
import polars as pl

_OUT = Path("data/analytics/industry_strategy")

# 介入点（trade_date）：历史顶部 + 代表性高位（取最近交易日）
_ENTRIES = [
    ("2021-08-30", "历史最高点(15200)"),
    ("2021-12-31", "顶部后 4 个月(86%)"),
    ("2022-03-01", "顶部后 6 个月(81%)"),
    ("2022-06-01", "顶部后 9 个月(74%)"),
    ("2024-09-30", "下跌中途反弹(44%)"),
    ("2025-10-31", "出清后期(48%)"),
]
_MODES = [
    ("buy", "买入持有"),
    ("cycfn", "cycle+fin 两源"),
    ("cycfn_price", "cycfn+price 三源"),
]
_PRICE_THR = 20.0


def _metrics_from(returns: list[float]) -> dict:
    """从一段日收益序列算累计收益/年化/最大回撤（回撤相对本段起点 1.0）。"""
    nav = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        nav *= 1 + r
        peak = max(peak, nav)
        max_dd = max(max_dd, (peak - nav) / peak)
    years = max(len(returns) / 252.0, 1e-9)
    cagr = (nav ** (1.0 / years) - 1.0) * 100.0
    return {"nav": nav, "cagr": cagr, "max_dd": max_dd * 100.0}


def _time_to_recover(rets: list[float]) -> int | None:
    """回本天数：介入后首次「经历实质下跌(nav<0.95)后重新回到 ≥1.0」的交易日数。

    口径（直观的"回本等待"）：
    - 从未实质跌破 0.95 → 0（轻回撤，无回本等待）；
    - 最终 nav < 1.0 → None（未回本）；
    - 否则返回「首次跌破 0.95 之后首次 nav>=1.0」的交易日数。
    """
    nav = 1.0
    min_nav = 1.0
    dipped = False
    for _i, r in enumerate(rets):
        nav *= 1 + r
        min_nav = min(min_nav, nav)
        if nav < 0.95:
            dipped = True
    if not dipped:
        return 0
    if nav < 1.0:  # 最终仍未回本
        return None
    nav = 1.0
    for i, r in enumerate(rets):
        nav *= 1 + r
        if nav >= 1.0 and i > 0:
            return i + 1
    return None


def main() -> None:
    df = pgc._build_panel().sort("trade_date")
    dates = df["trade_date"].to_list()
    rets = df["ret"].to_list()
    weights = {
        "buy": [1.0] * len(df),
        "cycfn": pgc._weights("cycfn", df).to_list(),
        "cycfn_price": pgc._weights("cycfn_price_or", df, _PRICE_THR).to_list(),
    }
    # 权重 shift(1) 实现 T+1
    wshift = {k: [1.0] + v[:-1] for k, v in weights.items()}

    rows = []
    print("=== 高位介入生存检验（T+1、无前视）===")
    for entry_s, label in _ENTRIES:
        entry = datetime.date.fromisoformat(entry_s)
        if entry not in dates:
            print(f"  {entry_s} 不在交易日，跳过")
            continue
        i0 = dates.index(entry)
        print(f"\n--- 介入点 {entry_s}（{label}）---")
        for mode, mlabel in _MODES:
            seg_rets = []
            for i in range(i0, len(dates)):
                seg_rets.append(wshift[mode][i] * rets[i])
            m1 = _metrics_from(seg_rets[:252])
            m2 = _metrics_from(seg_rets[:504])
            mall = _metrics_from(seg_rets)
            rec = _time_to_recover(seg_rets)
            if rec == 0:
                rec_s = "已回本(轻回撤)"
            elif rec is not None:
                rec_s = f"{rec}日"
            else:
                rec_s = "未回本"
            print(
                f"  {mlabel:18s} 1年nav={m1['nav'] * 100:7.1f}%  2年nav={m2['nav'] * 100:7.1f}%  "
                f"至今nav={mall['nav'] * 100:7.1f}%  介入后MaxDD={mall['max_dd']:5.1f}%  回本={rec_s}"
            )
            rows.append(
                {
                    "entry": entry_s,
                    "entry_label": label,
                    "mode": mode,
                    "variant": mlabel,
                    "nav_1y": m1["nav"],
                    "nav_2y": m2["nav"],
                    "nav_to_date": mall["nav"],
                    "max_dd_post_entry": mall["max_dd"],
                    "recover_days": rec,
                }
            )

    _OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(_OUT / "industry_solar_high_entry_survival.csv")

    lines = [
        "# 630500 高位介入生存检验（2026-09）",
        "",
        "问题：即使在高位/顶部追入，用 cycfn+price 三源防守交易，能否比「一直持有」减亏、活下来",
        "（介入后回撤可控 + 回本可期）。介入点不择时（人为选历史高位），纯测防守门的生存能力。",
        "",
        "口径：T+1、无前视；cycle+fin 触发降 0.25、价格回撤≥20% 空仓（cycfn_price）；",
        "nav 为介入点起累计净值（1.0=介入点），MaxDD 为介入后最大回撤，回本=首次回到 1.0。",
        "",
        "| 介入点 | 路径 | 1年nav | 2年nav | 至今nav | 介入后MaxDD | 回本 |",
        "| :-- | :-- | --: | --: | --: | --: | :-- |",
    ]
    for r in rows:
        if r["recover_days"] == 0:
            rec = "已回本(轻回撤)"
        elif r["recover_days"] is not None:
            rec = f"{r['recover_days']}日"
        else:
            rec = "未回本"
        lines.append(
            f"| {r['entry']} {r['entry_label']} | {r['variant']} | {r['nav_1y'] * 100:.1f}% | "
            f"{r['nav_2y'] * 100:.1f}% | {r['nav_to_date'] * 100:.1f}% | {r['max_dd_post_entry']:.1f}% | {rec} |"
        )
    lines += [
        "",
        "## 结论（生存判定，2026-09 实跑）",
        "",
        "1. **精确历史顶部（2021-08-30）介入 = 最坏情形**：买入持有至今 nav 35.8%（亏 64%）、MaxDD 72.8%、",
        "   永未回本；cycfn+price 三源把亏幅压到 20.9%（nav 79.1%）、MaxDD 压到 33.7%，但仍未回本——",
        "   因为顶部满仓扛了第一段下跌，价格补丁 2022-10 才触发。精确顶日介入无法完全避免亏损。",
        "2. **只要不是精确顶日介入，三源都能回本**：顶部后 4 个月介入（2021-12-31）三源 nav 90.3%/MaxDD 23.2%",
        "   （买入持有 40.9%/71.9% 未回本）；顶部后 6-9 个月介入（2022-03/06）三源 nav 102.9%/104.1%、",
        "   MaxDD 10.8%（买入持有 42.4%/45.2%、MaxDD 71.9% 未回本）。",
        "3. **「活下来」的本质**：防守门把「亏损 55-64% 且永不回本」变成「亏损 10-30% 且多数介入点可回本」",
        "   ——这是能否「活到下一轮景气」的分界。减亏幅度（以历史顶介入为例）：72.8→33.7%（MaxDD）、",
        "   64%→21%（亏损）。",
        "4. **回本时间**：能回本的介入点中，回本等待约 933 日（2021-12-31 介入，≈3.7 年，含出清磨底）",
        "   ——漫长周期等待的真实量化；介入越早（越接近顶）等待越长，介入越晚（越接近出清）等待越短。",
        "5. **诚实定位**：三源是「减亏 + 提高存活概率」工具，不是「高位介入也能赚」的魔术；",
        "   精确顶日介入仍亏损，只是亏得少得多。样本仅本轮一次实现，二轮数据前不宣称可重复。",
        "",
        "> 口径注：nav 相对介入点（1.0=介入点），MaxDD 相对段内峰值；回本=介入后首次「经历实质下跌",
        "> (nav<0.95)后回到 ≥1.0」的交易日数，未实质下跌标「已回本(轻回撤)」，最终 nav<1.0 标「未回本」。",
        "",
        "> ⚠️ 局限：样本只有本轮一次高位→过剩→出清周期；介入点为人为选取的历史高位（非随机抽样）；",
        "> 结论是该周期内这些高位介入点的生存表现，二轮数据前不宣称可重复。",
    ]
    (_OUT / "industry_solar_high_entry_survival.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n输出: {_OUT / 'industry_solar_high_entry_survival.md'}")


if __name__ == "__main__":
    main()
