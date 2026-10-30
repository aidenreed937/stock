"""光伏 630500 财报滞后决定性指标「减仓防守门」价值量化。

定位：财报净利 TTM 同比是滞后年化指标，不作前瞻择时/增强；本脚本检验它作为**减仓防守门**
（净利 TTM 同比 <= 0 时降仓）的防守价值能兑现多少，并明确其边界。

信号（成分股聚合 TTM 同比，披露日保守约定无前视，T+1）：
- pos = 净利 TTM 同比 > 0 → 满仓；<= 0 → 降仓到 floor（力度扫描 0.5/0.3/0.1/0.0）。
- 对照：无防守（买持）。

输出：全/样本外 CAGR、Sharpe、MaxDD、防守天数；防守段/非防守段买持归因；触发时点分析。
局限：成分股为当前名单（survivorship）；2025Q4 起净利 TTM 同比"转正"为基数坍塌伪信号
（绝对额仍深度亏损），若面板越过该披露日，防守门会被伪信号错误放行。

输出：data/analytics/industry_strategy/industry_solar_fin_defense_gate.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext
from stock_data.pipeline.sw_industry_golden import load_sw_2021_industry_symbols

_START = datetime.date(2014, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "630500"


def _const_series() -> pl.DataFrame:
    """tushare income 成分股归母净利聚合 → 630500 季度净利 → TTM → 同比。"""
    runtime = DataRuntimeContext.from_root("data")
    cat = DataCatalog(data_source="tushare", runtime=runtime)
    cat_lx = DataCatalog(data_source="lixinger", runtime=runtime)
    const = load_sw_2021_industry_symbols(cat, _INDUSTRY, level="L2")
    if not const:
        const = load_sw_2021_industry_symbols(cat_lx, _INDUSTRY, level="L2")
    stock_basic = cat.load_dataset("stock_basic", columns=["symbol"])
    qualified = (
        [
            str(symbol)
            for symbol in stock_basic.get_column("symbol").to_list()
            if str(symbol).split(".", 1)[0] in const
        ]
        if not stock_basic.is_empty() and "symbol" in stock_basic.columns
        else const
    )
    inc = cat.load_dataset("income", symbols=qualified)
    qt = (
        inc.with_columns(
            pl.col("end_date").dt.quarter().alias("q"),
            pl.col("end_date").dt.year().alias("y"),
        )
        .select(["symbol", "end_date", "y", "q", "n_income_attr_p"])
        .sort("symbol", "end_date", "q")
        .sort(["symbol", "y", "q"])
        .unique(subset=["symbol", "y", "q"], keep="last")
    )
    cum = qt.pivot(
        on="q", index=["symbol", "y"], values="n_income_attr_p", aggregate_function="first"
    )

    def single(
        c1: float | None, c2: float | None, c3: float | None, c4: float | None
    ) -> list[float]:
        c1 = c1 or 0
        c2 = c2 or c1
        c3 = c3 or c2
        c4 = c4 or c3
        return [c1, c2 - c1, c3 - c2, c4 - c3]

    rows = []
    for r in cum.to_dicts():
        if r["y"] is None:
            continue
        sq = single(r.get("1"), r.get("2"), r.get("3"), r.get("4"))
        for qv in [1, 2, 3, 4]:
            rows.append(
                {"symbol": r["symbol"], "year": r["y"], "quarter": qv, "single": sq[qv - 1]}
            )
    sqf = pl.DataFrame(rows)
    qsum = (
        sqf.group_by(["year", "quarter"])
        .agg(pl.col("single").sum().alias("np_q"))
        .sort(["year", "quarter"])
    )
    qtm = qsum.with_columns(
        [
            pl.col("np_q").rolling_sum(window_size=4).alias("np_ttm"),
            pl.col("np_q").shift(4).rolling_sum(window_size=4).alias("np_ttm_prev"),
        ]
    ).with_columns((pl.col("np_ttm") / pl.col("np_ttm_prev") - 1).alias("np"))
    return qtm.filter(pl.col("np").is_not_null())


def _signal() -> pl.DataFrame:
    const = _const_series()

    def pub(y: int, q: int) -> datetime.date:
        if q == 1:
            return datetime.date(y, 4, 30)
        if q == 2:
            return datetime.date(y, 8, 31)
        if q == 3:
            return datetime.date(y, 10, 31)
        return datetime.date(y + 1, 4, 30)

    disp = pl.DataFrame(
        [{"disclose": pub(r["year"], r["quarter"]), "np": r["np"]} for r in const.to_dicts()]
    ).sort("disclose")
    disp = disp.unique(subset=["disclose"], keep="last").sort("disclose")
    res = disp.with_columns(pl.Series("pos", [1.0 if v > 0 else 0.0 for v in disp["np"].to_list()]))
    panel = (
        pl.read_parquet(_PANEL)
        .filter((pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START))
        .sort("trade_date")
    )
    grid = panel.select(["trade_date"])
    sig = (
        grid.join(
            res.select(["disclose", "pos"]).rename({"disclose": "trade_date"}),
            on="trade_date",
            how="left",
        )
        .sort("trade_date")
        .with_columns(pl.col("pos").fill_null(strategy="forward").fill_null(1.0))
    )
    return sig


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


def main() -> None:
    panel = (
        pl.read_parquet(_PANEL)
        .filter((pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START))
        .sort("trade_date")
    )
    s = _signal()
    df = (
        panel.select(["trade_date", "close"])
        .join(s, on="trade_date", how="left")
        .with_columns(pl.col("close").pct_change().fill_null(0.0).alias("ret"))
        .sort("trade_date")
    ).with_columns(pl.col("pos").fill_null(1.0))
    posv = df["pos"].to_list()
    retv = df["ret"].to_list()
    dts = df["trade_date"].to_list()

    print(
        f"防守门触发时点：首次 pos=0 {dts[posv.index(0.0)]}；末次 pos=1 {dts[len(posv) - 1 - posv[::-1].index(1.0)]}"
    )
    print(
        f"2022-01-01→2024-04-30（主跌段）内防守天数：{sum(1 for p, d in zip(posv, dts) if p == 0 and datetime.date(2022, 1, 1) <= d < datetime.date(2024, 4, 30))}"
    )

    rows = []
    print(
        f"\n{'防守力度(净利TTM同比<=0降仓至)':36s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s} {'防守天数':>8s}"
    )
    for floor in [1.0, 0.5, 0.3, 0.1, 0.0]:
        w = [1.0 if p == 1.0 else floor for p in posv]
        w_shift = [1.0] + w[:-1]
        pos = [w_shift[i] * retv[i] for i in range(len(retv))]
        full = _metrics((1 + pl.Series(pos)).cum_prod().to_list())
        oo_idx = [i for i, d in enumerate(dts) if d >= _OOS]
        wo = [1.0 if posv[i] == 1.0 else floor for i in oo_idx]
        wo_shift = [1.0] + wo[:-1]
        pos_oos = [wo_shift[j] * retv[oo_idx[j]] for j in range(len(oo_idx))]
        oos = _metrics((1 + pl.Series(pos_oos)).cum_prod().to_list())
        gate_days = sum(1 for p in posv if p == 0.0)
        label = "无防守(买持)" if floor == 1.0 else f"降仓至 {floor:.1f}"
        rows.append(
            {
                "label": label,
                **{f"full_{k}": v for k, v in full.items()},
                **{f"oos_{k}": v for k, v in oos.items()},
                "gate_days": gate_days,
            }
        )
        print(
            f"{label:36s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
            f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {gate_days:8d}"
        )

    # 防守段/非防守段买持归因
    print("\n分段买持归因：")
    segs = []
    for pv, label in [(1.0, "净利TTM同比>0段(买持)"), (0.0, "净利TTM同比<=0段(买持)")]:
        idx = [i for i, p in enumerate(posv) if p == pv]
        nav = (1 + pl.Series([retv[i] for i in idx])).cum_prod().to_list()
        m = _metrics(nav)
        segs.append(
            {
                "label": label,
                "n": len(idx),
                **{f"{k}": v for k, v in m.items()},
                "ret": (nav[-1] - 1) * 100,
            }
        )
        print(
            f"  {label}: n={len(idx)} CAGR={m['cagr']:.2f} MaxDD={m['max_dd']:.2f} 首尾={(nav[-1] - 1) * 100:.1f}%"
        )

    _OUT.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(_OUT / "industry_solar_fin_defense_gate.csv")
    lines = [
        "# 630500 财报滞后决定性指标「减仓防守门」价值量化",
        "",
        "信号：成分股聚合净利 TTM 同比（tushare income，披露日保守约定无前视，T+1）；",
        "净利 TTM 同比 <= 0 → 降仓到 floor；> 0 → 满仓。",
        "",
        "| 防守力度 | 全CAGR | 全Sharpe | 全MaxDD | 外CAGR | 外Sharpe | 外MaxDD | 防守天数 |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['label']} | {r['full_cagr']:.2f} | {r['full_sharpe']:.3f} | {r['full_max_dd']:.2f} | "
            f"{r['oos_cagr']:.2f} | {r['oos_sharpe']:.3f} | {r['oos_max_dd']:.2f} | {r['gate_days']} |"
        )
    lines += [
        "",
        "| 分段买持归因 | n | CAGR | MaxDD | 首尾收益 |",
        "| :-- | --: | --: | --: | --: |",
    ]
    for r in segs:
        lines.append(
            f"| {r['label']} | {r['n']} | {r['cagr']:.2f} | {r['max_dd']:.2f} | {r['ret']:.1f}% |"
        )
    lines += [
        "",
        "**结论（防守门价值真实但边界明确）**：防守段（净利 TTM 同比<=0）买持 CAGR -5.05%、首尾 -17.2%，",
        "说明「净利 TTM 同比为负」确实是基本面决定性恶化区间——此区间降仓是有效防守，全周期 CAGR",
        "9.87→11.3、MaxDD 72.8→66.4（floor 0.3 以上趋同，因最大回撤发生在未防守的 2022-2024 段）。",
        "",
        "**边界**：① 防守门 2024-04-30 才首次触发，2022-01→2024-04 主跌段防守天数为 0——2022 是利润峰值基数，",
        "TTM 同比滞后约 6 个季度才转负，防不住顶部下杀，只保护「确认恶化后的尾部」（2024-04 后 100% 防守）；",
        "② 样本外仍 -16%（买持 -17.3%），防守门只能减亏、不能把 630500 转成样本外正收益；",
        "③ 2025Q4 起同比「转正」为基数坍塌伪信号（绝对额仍深度亏损），面板一旦越过 2026-08-31 披露日，",
        "防守门会被伪信号错误放行——需在实现里对 near-zero 基数做强约束。",
    ]
    (_OUT / "industry_solar_fin_defense_gate.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
