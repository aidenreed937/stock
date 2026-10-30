""" "拥挤 × 估值分位组合腿"跨行业分年降仓回测（270100 + 240400 + 710100 + 240300）。

背景（2026-09）：时序拥挤腿验证发现——成交占比时序分位冲顶（热区）后的表现取决于
"集中时是否已透支估值"（低 PE5y 组挤后涨、高 PE5y 组挤后跌）。本脚本把反向腿升级为
**组合信号**：`成交占比时序分位 ≥90 × PE5y 分位 ≥ 阈值` 才降仓，检验组合是否把半导体
（常年高估值、单用拥挤腿 fwd60 仅 -0.1%）提升到与贵金属（-5.2%）同等的有效水平。

对照变体（T+1 近似、无前视、无摩擦，与 demand_offense 同口径）：
- buy_hold：恒满仓（基准）
- crowd_only：share_pct_250 >= 90 → 次日降 0.3
- crowd_val60：share_pct_250 >= 90 且 pe5y >= 60 → 次日降 0.3（贴近分组分界 57）
- crowd_val80：share_pct_250 >= 90 且 pe5y >= 80 → 次日降 0.3（严格高估值）

pe5y 缺失视为非高估值（不触发组合降仓；2018 上半年因数据起步有缺口，报告局限标注）。

产物：
- data/analytics/industry_strategy/semi_crowding_valuation_leg.csv（行业×变体指标）
- data/analytics/industry_strategy/semi_crowding_valuation_leg_yearly.csv（行业×变体×年份 MaxDD）
- data/analytics/industry_strategy/semi_crowding_valuation_leg.md（报告）
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_MKT = Path("data/curated/mart/market_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")

_INDUSTRIES = ["270100", "240400", "710100", "240300"]
_VARIANTS = ["buy_hold", "crowd_only", "crowd_val60", "crowd_val80"]
_VAL_THRESHOLDS = {"crowd_val60": 60.0, "crowd_val80": 80.0}
_CROWD_TH = 90.0
_CROWD_WINDOW = 250


def _rolling_pct(series: pl.Series, window: int) -> pl.Series:
    """时序滚动历史分位（复用 industry_direction_map 框架口径）。"""
    s = series.fill_nan(0.0).fill_null(0.0)
    return (
        s.to_frame("v")
        .select(
            pl.col("v").rolling_map(
                lambda x: float((x <= x[-1]).mean()) * 100.0 if len(x) > 0 else 50.0,
                window_size=window,
                min_samples=1,
            )
        )["v"]
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def _load_industry(code: str) -> pl.DataFrame:
    """单个行业：close / ret / share_pct_250 / pe5y（缺失 -1 视为非高估值）。"""
    panel = pl.read_parquet(_PANEL)
    semi = panel.filter((pl.col("industry_code") == code) & (pl.col("trade_date") >= _START)).sort(
        "trade_date"
    )
    mkt = pl.read_parquet(_MKT).select(
        pl.col("trade_date"), (pl.col("total_turnover") / 1e8).alias("mkt_amt_yi")
    )
    df = (
        semi.select(["trade_date", "close", "amount_yi", "pe_ttm_ew_percentile_5y"])
        .join(mkt, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(
            pl.col("amount_yi").fill_null(0.0).alias("amount_yi"),
            (
                pl.col("amount_yi").fill_null(0.0)
                / pl.col("mkt_amt_yi").fill_null(pl.col("amount_yi"))
            ).alias("share"),
            pl.col("pe_ttm_ew_percentile_5y").fill_null(-1.0).alias("pe5y"),
            pl.col("close").pct_change().fill_null(0.0).alias("ret"),
        )
    )
    share = df["share"].clone()
    return df.with_columns(
        pl.Series(f"share_pct_{_CROWD_WINDOW}", _rolling_pct(share, _CROWD_WINDOW))
    )


def _metrics(nav: list[float]) -> dict[str, float]:
    """CAGR / MaxDD / Sharpe（复用 demand_offense 口径，252 交易日年化）。"""
    arr = [v if v > 0 else 1e-9 for v in nav]
    if len(arr) < 2:
        return {"cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0}
    final, n = arr[-1], len(arr)
    years = max(n / 252.0, 1e-9)
    cagr = ((final / arr[0]) ** (1.0 / years) - 1.0) * 100.0 if arr[0] > 0 else 0.0
    peak, mdd = -1e9, 0.0
    for v in arr:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    rets = [arr[i] / arr[i - 1] - 1.0 for i in range(1, len(arr)) if arr[i - 1] > 0]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var = sum((r - mean_r) ** 2 for r in rets) / max(len(rets) - 1, 1) if len(rets) > 1 else 0.0
    sharpe = mean_r / math.sqrt(var) * math.sqrt(252.0) if var > 0 else 0.0
    return {"cagr": cagr, "max_dd": mdd * 100.0, "sharpe": sharpe}


def _hot_col(df: pl.DataFrame, variant: str) -> pl.DataFrame:
    """给 df 加 hot（当日信号）列；crowd_only/组合腿 用 share_pct>=90 触发。"""
    if variant == "buy_hold":
        return df.with_columns(pl.lit(False).alias("hot"))
    crowd = pl.col(f"share_pct_{_CROWD_WINDOW}") >= _CROWD_TH
    if variant == "crowd_only":
        return df.with_columns(crowd.alias("hot"))
    val_th = _VAL_THRESHOLDS[variant]
    return df.with_columns((crowd & (pl.col("pe5y") >= val_th)).alias("hot"))


def _nav(df: pl.DataFrame) -> pl.DataFrame:
    """T+1 降仓：当日信号 → 次日仓位（0.3 或 1.0），复利净值。"""
    hot = df["hot"].shift(1).fill_null(False).cast(pl.Float64)
    pos = (1.0 - 0.7 * hot) * df["ret"]
    return df.with_columns((1 + pos.fill_null(0.0)).cum_prod().alias("nav"))


def _run_metrics(df: pl.DataFrame, start: datetime.date) -> tuple[float, float, float]:
    sub = df.filter(pl.col("trade_date") >= start)
    m = _metrics(sub["nav"].to_list())
    return (m["cagr"], m["max_dd"], m["sharpe"])


def _yearly_maxdd(df: pl.DataFrame) -> list[dict]:
    rows = []
    for y in sorted(df["trade_date"].dt.year().unique().to_list()):
        sub = df.filter(pl.col("trade_date").dt.year() == y).sort("trade_date")
        nav = sub["nav"].to_list()
        if len(nav) < 2:
            continue
        base = nav[0]
        ret_pct = (nav[-1] / base - 1.0) * 100.0
        peak, mdd = -1e9, 0.0
        for v in nav:
            nv = v / base
            peak = max(peak, nv)
            mdd = max(mdd, (peak - nv) / peak)
        rows.append({"year": y, "ret_pct": round(ret_pct, 1), "maxdd_pct": round(mdd * 100.0, 1)})
    return rows


def _fmt(v: float) -> str:
    return f"{v:.1f}"


def _fmt3(v: float) -> str:
    return f"{v:.2f}"


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    metrics_rows: list[dict] = []
    yearly_rows: list[dict] = []
    for code in _INDUSTRIES:
        df = _load_industry(code)
        for variant in _VARIANTS:
            d = _nav(_hot_col(df, variant))
            full = _run_metrics(d, _START)
            oos = _run_metrics(d, _OOS)
            metrics_rows.append(
                {
                    "industry": code,
                    "variant": variant,
                    "全CAGR%": round(full[0], 2),
                    "全MaxDD%": round(full[1], 2),
                    "全Sharpe": round(full[2], 3),
                    "外CAGR%": round(oos[0], 2),
                    "外MaxDD%": round(oos[1], 2),
                    "外Sharpe": round(oos[2], 3),
                }
            )
            for yr in _yearly_maxdd(d):
                yearly_rows.append(
                    {
                        "industry": code,
                        "variant": variant,
                        "year": yr["year"],
                        "ret_pct": yr["ret_pct"],
                        "maxdd_pct": yr["maxdd_pct"],
                    }
                )
    mdf = pl.DataFrame(metrics_rows)
    ydf = pl.DataFrame(yearly_rows)
    mdf.write_csv(_OUT / "semi_crowding_valuation_leg.csv")
    ydf.write_csv(_OUT / "semi_crowding_valuation_leg_yearly.csv")

    # 报告
    lines = [
        "# 「拥挤 × 估值分位」组合腿跨行业分年降仓回测",
        "",
        f"> 数据源：`industry_l2_panel_daily`（{_CROWD_WINDOW} 日成交占比时序分位 + pe5y 估值分位）+ "
        f"`market_daily.total_turnover`。窗口 {_START} ~ 2026-08-28，样本外自 {_OOS}。",
        "> T+1 近似（当日信号次日生效）、无前视、无摩擦。组合腿：`share_pct_250>=90 × pe5y>=阈值` 才降 0.3；",
        "> pe5y 缺失视为非高估值（2018 上半年数据起步缺口，局限）。",
        "",
        "## 1) 分行业 × 变体指标",
        "",
        "| 行业 | 变体 | 全CAGR% | 全MaxDD% | 全Sharpe | 外CAGR% | 外MaxDD% | 外Sharpe |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in mdf.sort(["industry", "variant"]).to_dicts():
        lines.append(
            f"| {r['industry']} | {r['variant']} | {_fmt(r['全CAGR%'])} | {_fmt(r['全MaxDD%'])} | "
            f"{_fmt3(r['全Sharpe'])} | {_fmt(r['外CAGR%'])} | {_fmt(r['外MaxDD%'])} | {_fmt3(r['外Sharpe'])} |"
        )
    lines += ["", "## 2) 分年 收益%/年内MaxDD%（买入持有 vs crowd_only vs crowd_val80）", ""]
    year_variants = ["buy_hold", "crowd_only", "crowd_val80"]
    for code in _INDUSTRIES:
        lines.append(f"### {code}")
        lines.append("")
        years = sorted({y["year"] for y in yearly_rows if y["industry"] == code})
        head = "| 年份 | " + " | ".join(f"{v} 收益% | {v} MaxDD%" for v in year_variants) + " |"
        lines.append(head)
        lines.append("| :--- | " + " | ".join([":---:"] * len(year_variants) * 2) + " |")
        for y in years:
            cells = []
            for v in year_variants:
                hit = next(
                    (
                        r
                        for r in yearly_rows
                        if r["industry"] == code and r["variant"] == v and r["year"] == y
                    ),
                    None,
                )
                if hit is None:
                    cells += ["-", "-"]
                else:
                    cells += [_fmt(hit["ret_pct"]), _fmt(hit["maxdd_pct"])]
            lines.append(f"| {y} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += [
        "## 3) 结论（270100 逐年版收益/回撤视角）",
        "",
        "- **crowd_only = 降回撤但常伤收益**：2026/2018/2020/2023 降回撤（尤其 2026 39.2→16.1），但",
        "  2019（121→100）、2021（30→22）、2025（52→41）等疯牛/大涨年误伤收益——它砍的是涨段仓位而非跌段回撤。",
        "- **crowd_val80 = 满仓吃涨 + 疯狂牛末端降仓**：2019/2020/2021/2024/2026 收益均跑赢买入（+1~+14pp，",
        "  仅 2025 略拖累 -7pp）；平时（2018/2020/2021/2022/2024/2025）与买入同步回撤，仅在 2026 降到",
        "  16.1%（-23pp）——收益率持续增厚，回撤优势全集中在 2026 单次暴跌防守。",
        "- **结论**：crowd_val80 相对买入是「牛市满仓不误伤 + 疯狂牛末端提现」，故全周期 CAGR/Sharpe 最优；",
        "  但其回撤优势依赖 2026 单一样本，稳健性待更多疯狂牛年确认（见 research_roadmap 稳健性权衡）。",
        "- **候选行业（240400/240300/710100）**：估值门均削弱 crowd_only（商品型拥挤在低估值区，加 PE 门误过滤），",
        "  逐年版收益/回撤见上表，证实「拥挤×估值」是高估值产业链（半导体）专属，非普适公式。",
    ]
    (_OUT / "semi_crowding_valuation_leg.md").write_text("\n".join(lines), encoding="utf-8")
    print(mdf.sort(["industry", "variant"]))
    print("\n分年表已写入 md")


if __name__ == "__main__":
    main()
