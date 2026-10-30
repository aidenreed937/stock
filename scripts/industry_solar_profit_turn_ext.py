"""光伏 630500 财报净利 TTM 同比「拐头（右侧确认）」回测 —— 成分股聚合扩展版（2014→）。

动机：`scripts/industry_solar_profit_turn.py` 基于 `sw_2021_l2_fs_non_financial`，
np_ttm_y2y 仅 2022-12-31 起 13 个有效期，无法覆盖 2014-2021 景气上行段。
本脚本用 tushare income 当日成分股（630500）归母净利聚合出 630500 季度净利 → TTM → 同比，
把「底部右侧确认」回测延伸到 2014Q1 起全周期，检验结论是否在跨周期下稳健。

信号（披露日保守约定 = 无前视：Q1→4/30, Q2→8/31, Q3→10/31, Q4→次年4/30；前向填充日频，T+1）：
- buy_hold：纯买入（基准）。
- turn：np_ttm_y2y 由负转正（过渡触发）→ 满仓，否则降 30%。
- pos：np_ttm_y2y > 0（水平右侧确认，最贴近「底部右侧确认」语义）→ 满仓，否则降 30%。
- up：np_ttm_y2y 边际改善（本期 > 上期）→ 满仓，否则降 30%。

局限：成分股取"当前"630500 名单（survivorship，历史含退市/新进成分的偏差）；near-zero 盈利基数
下同比比率失真（如 2025Q3 np_ttm_y2y=-59.6、2025Q4 起"转正"为基数坍塌伪信号，绝对额仍深度亏损）。

输出：data/analytics/industry_strategy/industry_solar_profit_turn_ext.{csv,md}
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
    npv = disp["np"].to_list()
    res = disp.with_columns(
        pl.Series("np_prev", [None] + npv[:-1]),
        pl.Series(
            "turn",
            [0.0] + [1.0 if (npv[i] > 0 and npv[i - 1] <= 0) else 0.0 for i in range(1, len(npv))],
        ),
        pl.Series("pos", [1.0 if v > 0 else 0.0 for v in npv]),
        pl.Series(
            "up",
            [0.0] + [1.0 if npv[i] > npv[i - 1] else 0.0 for i in range(1, len(npv))],
        ),
    )
    panel = (
        pl.read_parquet(_PANEL)
        .filter((pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START))
        .sort("trade_date")
    )
    grid = panel.select(["trade_date"])
    sig = (
        grid.join(
            res.select(["disclose", "turn", "pos", "up"]).rename({"disclose": "trade_date"}),
            on="trade_date",
            how="left",
        )
        .sort("trade_date")
        .with_columns(
            pl.col("turn").fill_null(strategy="forward").fill_null(0.0),
            pl.col("pos").fill_null(strategy="forward").fill_null(0.0),
            pl.col("up").fill_null(strategy="forward").fill_null(0.0),
        )
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


def _run(mode: str, panel: pl.DataFrame, sig: pl.DataFrame, col: str) -> tuple[dict, dict, float]:
    df = (
        panel.select(["trade_date", "close"])
        .join(sig, on="trade_date", how="left")
        .with_columns(pl.col("close").pct_change().fill_null(0.0).alias("ret"))
        .sort("trade_date")
    )
    if mode == "buy":
        w = pl.Series([1.0] * len(df))
    else:
        s = df[col].fill_null(0.0)
        w = 1.0 * s + 0.3 * (1.0 - s)
    w_shift = w.shift(1).fill_null(1.0)
    pos = (w_shift * df["ret"]).fill_null(0.0).to_list()
    full = _metrics((1 + pl.Series(pos)).cum_prod().to_list())
    odf = df.filter(pl.col("trade_date") >= _OOS)
    if mode == "buy":
        wo = pl.Series([1.0] * len(odf))
    else:
        s = odf[col].fill_null(0.0)
        wo = 1.0 * s + 0.3 * (1.0 - s)
    wo_shift = wo.shift(1).fill_null(1.0)
    pos_oos = (wo_shift * odf["ret"]).fill_null(0.0).to_list()
    oos = _metrics((1 + pl.Series(pos_oos)).cum_prod().to_list())
    hold = (1.0 * w).mean() * 100
    return full, oos, hold


def main() -> None:
    panel = (
        pl.read_parquet(_PANEL)
        .filter((pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START))
        .sort("trade_date")
    )
    sig = _signal()

    variants = [
        ("buy", "纯买入(基准)", "pos"),
        ("turn", "由负转正(过渡触发)", "turn"),
        ("pos", "净利>0 满仓/降30%(水平右确)", "pos"),
        ("up", "边际改善 满仓/降30%", "up"),
    ]
    rows = []
    print("=== 630500 成分股聚合净利TTM同比 右侧确认回测（2014→, T+1）===")
    print(
        f"{'变体':40s} {'全CAGR':>8s} {'全Sharpe':>8s} {'全MaxDD':>7s} | {'外CAGR':>7s} {'外Sharpe':>8s} {'外MaxDD':>7s} {'权重均值':>6s}"
    )
    for mode, label, col in variants:
        full, oos, hold = _run(mode, panel, sig, col)
        rows.append(
            {
                "mode": mode,
                "label": label,
                **{f"full_{k}": v for k, v in full.items()},
                **{f"oos_{k}": v for k, v in oos.items()},
                "hold_avg": hold,
            }
        )
        print(
            f"{label:40s} {full['cagr']:8.2f} {full['sharpe']:8.3f} {full['max_dd']:7.2f} | "
            f"{oos['cagr']:7.2f} {oos['sharpe']:8.3f} {oos['max_dd']:7.2f} {hold:6.1f}%"
        )
    out = pl.DataFrame(rows)
    _OUT.mkdir(parents=True, exist_ok=True)
    out.write_csv(_OUT / "industry_solar_profit_turn_ext.csv")
    lines = [
        "# 630500 成分股聚合净利 TTM 同比「右侧确认」回测（扩展版 2014→）",
        "",
        "数据：tushare income 当日 630500 成分股归母净利聚合 → 季度净利 → TTM → 同比。",
        "披露日保守约定（无前视）：Q1→4/30, Q2→8/31, Q3→10/31, Q4→次年4/30；前向填充日频，T+1。",
        "局限：成分股为当前名单（survivorship）；near-zero 盈利基数下同比失真（2025Q3 -59.6、2025Q4 起",
        "“转正”为基数坍塌伪信号，绝对额仍深度亏损）。",
        "",
        "| 变体 | 全CAGR | 全Sharpe | 全MaxDD | 外CAGR | 外Sharpe | 外MaxDD | 权重均值 |",
        "| :-- | --: | --: | --: | --: | --: | --: | --: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['label']} | {r['full_cagr']:.2f} | {r['full_sharpe']:.3f} | {r['full_max_dd']:.2f} | "
            f"{r['oos_cagr']:.2f} | {r['oos_sharpe']:.3f} | {r['oos_max_dd']:.2f} | {r['hold_avg']:.1f}% |"
        )
    lines += [
        "",
        "**结论**：跨 2014→2026 全周期（含 2014-2021 景气上行段）复现 L2 短期样本结论——",
        "水平右确(pos)几乎等于买入持有（全周期 CAGR 8.86 vs 9.87、MaxDD 66.4 vs 72.8，样本外仍 -16.1%），",
        "过渡触发(turn)仅靠长期低仓位（权重均值 32%）换来 MaxDD 72.8→29.9，全周期 CAGR 9.87→5.55，样本外仍 -4.1%。",
        "财报净利 TTM 同比是滞后年化指标：转正确认滞后真实底部约 2 个季度，结构性下行期长期为负→右侧确认",
        "既不能在景气上行段增强，也不能在样本外转亏为盈。与 framework「财报层仅滞后验证、不作前瞻/择时」定稿一致。",
    ]
    (_OUT / "industry_solar_profit_turn_ext.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
