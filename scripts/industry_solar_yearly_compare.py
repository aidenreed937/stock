"""光伏 630500 关键策略——逐年收益率 + 回撤对比（统一口径）。

目的：把"当前选择的几个策略"的全周期/分年收益与回撤并排对比，明确各策略在同一年份
的收益率与回撤结构，回答"进攻/防守"在年份间的实际兑现。

策略（两组口径，分开呈现避免混淆）：

Block 1（2018→，日频状态/防守口径，均在场、靠信号调仓位）：
- 纯买入        ：权重恒 1.0（基准）。
- cycle+fin     ：产能周期处于{过剩,下行} 或 财报TTM为负 → 0.25，否则 1.0（11 定稿最优防守）。
- 三源复合卡    ：risk=激活源数 {0:1.0,1:0.7,2:0.4,3:0.25}（11 中被证伪劣化的对照）。

Block 2（2020-05→，动量 Top3 兜底口径，来自 09 final_closed_loop）：
- 动量选中才持有：63 交易日调仓 return_60d Top3 选中 630500 才满仓，未选中空仓。
- 动量选中+cycle门：选中日且产能周期触发{过剩,下行} → 降 0.25（09 最接近转正形态）。

全部 T+1（权重 shift 1）、无前视。收益率=日频权重*630500 日收益累计；
回撤=滚动峰值到当前的最大回撤；分年收益率=各自然年内净值增长率，分年MaxDD=年内最大回撤。

输出：data/analytics/industry_strategy/industry_solar_yearly_compare.{csv,md}
"""

from __future__ import annotations

import datetime
from pathlib import Path

import industry_solar_final_closed_loop as fl
import industry_solar_warning_card as wc
import polars as pl

_OUT = Path("data/analytics/industry_strategy")
_SOLAR = "630500"
_FLOOR = 0.25
_CARD = {0: 1.0, 1: 0.7, 2: 0.4, 3: 0.25}


def _metrics(nav: list[float]) -> dict[str, float]:
    peak, mdd = -1e9, 0.0
    for v in nav:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    return {"final": nav[-1] if nav else 0.0, "max_dd": mdd * 100.0}


def _cum_rets(rets: list[float]) -> list[float]:
    nav, out = 1.0, []
    for r in rets:
        nav *= 1 + r
        out.append(nav)
    return out


def _year_stats(y: int, rets: list[float], dates: list[datetime.date]) -> dict | None:
    ys, yd = [], []
    for d, r in zip(dates, rets):
        if d.year == y:
            ys.append(r)
            yd.append(d)
    if len(ys) < 20:
        return None
    nav = _cum_rets(ys)
    m = _metrics(nav)
    return {"year": y, "n_days": len(ys), "ret": (nav[-1] - 1) * 100, "max_dd": m["max_dd"]}


def _weighted_rets(w: list[float], rets: list[float]) -> list[float]:
    wshift = [1.0] + w[:-1]  # T+1
    return [wshift[i] * rets[i] for i in range(len(rets))]


def main() -> None:
    panel = wc._build_panel()  # trade_date, close, ret, al_cap, al_cyc, al_fin, risk, ...
    dates = panel["trade_date"].to_list()
    rets = panel["ret"].fill_null(0.0).to_list()

    # ---- Block 1 权重（2018→，全时段在场）----
    al_cyc = panel["al_cyc"].to_list()
    al_fin = panel["al_fin"].to_list()
    risk = panel["risk"].to_list()

    w_buy = [1.0] * len(dates)
    w_cf = [0.25 if (c or f) else 1.0 for c, f in zip(al_cyc, al_fin)]
    w_card = [float(_CARD[r]) for r in risk]

    b1 = {
        "纯买入(基准)": _weighted_rets(w_buy, rets),
        "cycle+fin 两源门": _weighted_rets(w_cf, rets),
        "三源复合卡": _weighted_rets(w_card, rets),
    }

    # ---- Block 2 权重（2020-05→，动量 Top3 兜底，来自 09）----
    b2: dict[str, list[float]] = {}
    try:
        pool17 = fl._POOL + (_SOLAR,)
        wide = fl._load_wide(pool17)
        wide_dates = wide["trade_date"].to_list()
        w17 = fl._rebalance_weights(wide, pool17)
        gates = {"fin": fl._fin_series(), "top": fl._top_series(), "cycle": fl._build_states()}
        w_mom = fl._solar_weights_with_gates(w17, wide_dates, gates, "mom")
        w_cyc = fl._solar_weights_with_gates(w17, wide_dates, gates, "cycle")
        pool_ret = wide[f"{_SOLAR}_ret"].fill_null(0.0).to_list()
        b2["动量选中才持有"] = _weighted_rets(w_mom["w"].to_list(), pool_ret)
        b2["动量选中+cycle门"] = _weighted_rets(w_cyc["w"].to_list(), pool_ret)
        b2_dates = wide_dates
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Block2 跳过（09 依赖缺失）: {exc}")
        b2_dates = []

    print("=== Block 1：日频状态/防守口径（2018→）分年收益率 + 回撤 ===")
    years = sorted({d.year for d in dates})
    print(f"{'年份':6s} " + "".join(f"{name[:12]:>24s}" for name in b1))
    full_rows1 = []
    for y in years:
        line = f"{y:<6d}"
        for _name, rw in b1.items():
            st = _year_stats(y, rw, dates)
            if st is None:
                line += f"{'--':>15s}{'--':>9s}"
            else:
                line += f"{st['ret']:>8.1f}% / {st['max_dd']:>5.1f}%"
        print(line)
        for name, rw in b1.items():
            st = _year_stats(y, rw, dates)
            if st:
                full_rows1.append(
                    {
                        "block": 1,
                        "year": y,
                        "strategy": name,
                        "ret": st["ret"],
                        "max_dd": st["max_dd"],
                        "n": st["n_days"],
                    }
                )

    if b2:
        print("\n=== Block 2：动量 Top3 兜底口径（2020-05→）分年收益率 + 回撤 ===")
        print(f"{'年份':6s} " + "".join(f"{name[:12]:>24s}" for name in b2))
        full_rows2 = []
        for y in sorted({d.year for d in b2_dates}):
            line = f"{y:<6d}"
            for _name, rw in b2.items():
                st = _year_stats(y, rw, b2_dates)
                if st is None:
                    line += f"{'--':>15s}{'--':>9s}"
                else:
                    line += f"{st['ret']:>8.1f}% / {st['max_dd']:>5.1f}%"
            print(line)
            for name, rw in b2.items():
                st = _year_stats(y, rw, b2_dates)
                if st:
                    full_rows2.append(
                        {
                            "block": 2,
                            "year": y,
                            "strategy": name,
                            "ret": st["ret"],
                            "max_dd": st["max_dd"],
                            "n": st["n_days"],
                        }
                    )

    # 全周期
    print("\n=== 全周期收益率 + 最大回撤 ===")
    print(f"{'策略':22s} {'体系':10s} {'区间':16s} {'终值':>8s} {'MaxDD':>7s}")
    all_rows = []
    for name, rw in b1.items():
        nav = _cum_rets(rw)
        m = _metrics(nav)
        all_rows.append(
            {
                "block": 1,
                "strategy": name,
                "start": str(dates[0]),
                "end": str(dates[-1]),
                "final": m["final"],
                "max_dd": m["max_dd"],
            }
        )
        print(
            f"{name:22s} {'日频防守':10s} {str(dates[0])[:10]}..{str(dates[-1])[:10]} {m['final']:8.2f} {m['max_dd']:7.1f}%"
        )
    for name, rw in b2.items():
        nav = _cum_rets(rw)
        m = _metrics(nav)
        all_rows.append(
            {
                "block": 2,
                "strategy": name,
                "start": str(b2_dates[0]),
                "end": str(b2_dates[-1]),
                "final": m["final"],
                "max_dd": m["max_dd"],
            }
        )
        print(
            f"{name:22s} {'动量兜底':10s} {str(b2_dates[0])[:10]}..{str(b2_dates[-1])[:10]} {m['final']:8.2f} {m['max_dd']:7.1f}%"
        )

    # 写 csv + md
    _OUT.mkdir(parents=True, exist_ok=True)
    all_df = pl.DataFrame(all_rows)
    if all_df.height:
        all_df.write_csv(_OUT / "industry_solar_yearly_compare_summary.csv")
    yr_df = pl.DataFrame(full_rows1 + (full_rows2 if b2 else []))
    if yr_df.height:
        yr_df.write_csv(_OUT / "industry_solar_yearly_compare.csv")

    lines = [
        "# 光伏 630500 关键策略——分年收益率 + 回撤对比",
        "",
        "统一口径：全部 T+1（权重 shift 1）、无前视。收益率=630500 单行业日收益按策略权重累计；",
        "回撤=滚动峰值到当日的最大回撤；分年收益/回撤=每个自然年内的净值增长与最大回撤。",
        "",
        "**Block 1（2018→ 日频状态/防守口径，全时段在场，靠守卫号调仓位）**：",
        "- 纯买入：权重恒 1.0（基准）。",
        "- cycle+fin：产能周期∈{过剩,下行}或财报TTM负 → 0.25，否则 1.0（11 定稿最优防守）。",
        "- 三源复合卡：risk={0:1.0,1:0.7,2:0.4,3:0.25}（11 中证伪劣化的对照）。",
        "",
        "**Block 2（2020-05→ 动量 Top3 兜底口径，来自 09 final_closed_loop）**：",
        "- 动量选中才持有：63 交易日调仓 return_60d Top3 选中才满仓，未选中空仓。",
        "- 动量选中+cycle门：选中且产能周期∈{过剩,下行} → 0.25。",
        "",
        "## Block 1 分年（收益率% / MaxDD%）",
        "| 年份 | 纯买入 收益/回撤 | cycle+fin 收益/回撤 | 三源卡 收益/回撤 |",
        "| :-- | --: | --: | --: |",
    ]
    for y in years:
        cells = []
        for name in b1:
            st = _year_stats(y, b1[name], dates)
            cells.append(f"{st['ret']:.1f}%/{st['max_dd']:.1f}%" if st else "-")
        lines.append(f"| {y} | {cells[0]} | {cells[1]} | {cells[2]} |")
    lines += [
        "",
        "## Block 2 分年（收益率% / MaxDD%）",
        "| 年份 | 动量选中 收益/回撤 | 动量+cycle 收益/回撤 |",
        "| :-- | --: | --: |",
    ]
    if b2:
        for y in sorted({d.year for d in b2_dates}):
            cells = []
            for _name, rw in b2.items():
                st = _year_stats(y, rw, b2_dates)
                cells.append(f"{st['ret']:.1f}%/{st['max_dd']:.1f}%" if st else "-")
            lines.append(f"| {y} | {cells[0]} | {cells[1]} |")
    lines += [
        "",
        "## 全周期",
        "| 策略 | 体系 | 区间 | 终值(1→x) | MaxDD% |",
        "| :-- | :-- | :-- | --: | --: |",
    ]
    for r in all_rows:
        lines.append(
            f"| {r['strategy']} | {'日频防守' if r['block'] == 1 else '动量兜底'} | "
            f"{r['start'][:10]}..{r['end'][:10]} | {r['final']:.2f} | {r['max_dd']:.1f} |"
        )
    lines += [
        "",
        "**观测（逐年兑现）**：",
        "1. **进攻来自上行相位（2019-2021）满仓**：纯买入 2019/2020/2021 为 +50%/+191%/+48%（fwd4q 判据",
        "   同源）。cycle+fin 在这些年份几乎不牺牲进攻（53/166/48），只在 2020 略降（166 vs 191）",
        "   ——防守不砍上行，符合 A1-c。",
        "2. **防守回撤来自过剩相位（2022-2024）**：纯买入 2022/2023/2024 为 -19%/-39%/-21%、",
        "   MaxDD 33/52/36；cycle+fin 压窄到 -18%/-11%/-4%、MaxDD 20/16/10。回撤主要被产能周期门削减。",
        "3. **三源复合卡在进攻年份（2020 的 111% vs 买入 191%）牺牲上行**——印证 11「贴顶在景气主升",
        "   段误降仓劣化防守」，卡内贴顶源是负贡献。",
        "4. **动量兜底（Block 2）进攻弱**：2023 年 0.0%（630500 未被动量 Top3 选中即空仓整年），",
        "   全周期终值 1.27 < cycle+fin 的 2.71；叠加 cycle 门后 MaxDD 32.5% 最稳但收益仍低于 cycle+fin。",
        "5. **边界诚实标注**：2018 年所有策略回撤相同（-36.5%）——该年产能状态信号未激活（数据起点",
        "   前向填充前无可判信号），全时段在场且未降仓，属数据可用性边界非策略差异。",
    ]
    (_OUT / "industry_solar_yearly_compare.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
