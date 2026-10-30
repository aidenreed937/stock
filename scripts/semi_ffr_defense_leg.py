"""加息降息特征（ffr_chg_6m）接入半导体深研线的独立防守腿研究（270100）。

背景（2026-09）：宏观风控/方向池已实证加息期对 A 股成长压制（ffr_chg_6m 对 270100
全周期 IC -0.28~-0.30、样本外 -0.35~-0.37，本仓复算）；方向池 guarded_hike 样本外
Sharpe 0.48→0.61。本脚本检验：加息腿作为深研线**独立防守腿**（leg_type 独立分组、
不并入剪刀差）与既有防守门（scissors<0/DOI≥70）正交叠加的增量。

变体（T+1 次日生效、无前视、无摩擦，与 offense_defense_crowd 同口径）：
- buy_hold：恒满仓
- defense：剪刀差<0 或 DOI≥70 → 0.3（既有基本防守）
- defense_ffr：defense × 加息腿（ffr6m≥0.25pp → 0.3），任一触发→0.3、双触发→0
- offense_def：offense × defense（进攻+基本防守）
- offense_def_ffr：offense × defense_ffr（进攻+防守+加息腿）
- offense_defcrowd_ffr：offense × defense_crowd × 加息腿（三层+加息）

加息腿口径：FRED FEDFUNDS 月频 diff(6)（pp，带符号），asof backward 对齐日频，
与 CLI/宏观管线同源；缺失回退 0（不触发）。阈值 0.25pp 沿用方向池 guarded_hike
既定参数，不重炒。

产物：data/analytics/industry_strategy/semi_ffr_defense_leg.{csv,md}
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl
from scipy import stats

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_LEGS = Path("data/curated/mart/semiconductor_supply_legs.parquet")
_MKT = Path("data/curated/mart/market_daily.parquet")
_FRED = Path("data/curated/fred/market=US/macro_indicators/data.parquet")
_OUT = Path("data/analytics/industry_strategy")

_DOI_TH = 70.0
_DEMAND_TH = 70.0
_HIKE_TH = 0.25  # pp，与方向池 guarded_hike 同参
_CROWD_TH = 90.0
_VAL_TH = 80.0
_CROWD_WINDOW = 250
_VARIANTS = [
    "buy_hold",
    "defense",
    "defense_hike_single",
    "defense_double",
    "defense_ffr",
    "offense_def",
    "offense_def_double",
    "offense_def_ffr",
    "offense_defcrowd_ffr",
]


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


def _load() -> pl.DataFrame:
    """270100 日频：close/ret/demand/scissors/DOI/share_pct_250/pe5y/ffr_chg_6m + 触发位。"""
    panel = pl.read_parquet(_PANEL)
    semi = panel.filter(
        (pl.col("industry_code") == "270100") & (pl.col("trade_date") >= _START)
    ).sort("trade_date")
    legs = (
        pl.read_parquet(_LEGS)
        .filter((pl.col("industry_code") == "270100") & (pl.col("trade_date") >= _START))
        .select(["trade_date", "inventory_score"])
        .sort("trade_date")
    )
    mkt = pl.read_parquet(_MKT).select(
        pl.col("trade_date"), (pl.col("total_turnover") / 1e8).alias("mkt_amt_yi")
    )
    # 加息特征：FRED FEDFUNDS 月频 diff(6)，asof backward 对齐日频（同 CLI/宏观管线口径）
    mi = pl.read_parquet(_FRED)
    ffr = (
        mi.filter(pl.col("symbol") == "FEDFUNDS")
        .select(["trade_date", pl.col("value").alias("ffr")])
        .sort("trade_date")
        .with_columns(pl.col("ffr").diff(6).alias("ffr_chg_6m"))
        .select(["trade_date", "ffr_chg_6m"])
        .drop_nulls()
    )
    df = (
        semi.select(
            [
                "trade_date",
                "close",
                "amount_yi",
                "pe_ttm_ew_percentile_5y",
                "demand_score",
                "scissors_score",
            ]
        )
        .join(legs, on="trade_date", how="left")
        .join(mkt, on="trade_date", how="left")
        .sort("trade_date")
        .join_asof(ffr, on="trade_date", strategy="backward")
        .with_columns(
            pl.col("amount_yi").fill_null(0.0).alias("amount_yi"),
            (
                pl.col("amount_yi").fill_null(0.0)
                / pl.col("mkt_amt_yi").fill_null(pl.col("amount_yi"))
            ).alias("share"),
            pl.col("pe_ttm_ew_percentile_5y").fill_null(-1.0).alias("pe5y"),
            pl.col("inventory_score").fill_null(-1.0).alias("doi"),
            pl.col("demand_score").fill_null(50.0).alias("demand"),
            pl.col("scissors_score").fill_null(-99.0).alias("scissors"),
            pl.col("ffr_chg_6m").fill_null(0.0).alias("ffr6m"),
            pl.col("close").pct_change().fill_null(0.0).alias("ret"),
        )
    )
    share = df["share"].clone()
    return df.with_columns(
        pl.Series(f"share_pct_{_CROWD_WINDOW}", _rolling_pct(share, _CROWD_WINDOW))
    )


def _weights(df: pl.DataFrame, variant: str) -> pl.DataFrame:
    """各变体当日目标权重列 weight（T+1 在 _nav 中 shift 生效）。"""
    offense = ((pl.col("demand") >= _DEMAND_TH) & (pl.col("scissors") >= 0.0)).cast(pl.Float64)
    defense = ((pl.col("scissors") < 0.0) | (pl.col("doi") >= _DOI_TH)).cast(pl.Float64)
    hike = (pl.col("ffr6m") >= _HIKE_TH).cast(pl.Float64)
    crowd = (
        (pl.col(f"share_pct_{_CROWD_WINDOW}") >= _CROWD_TH) & (pl.col("pe5y") >= _VAL_TH)
    ).cast(pl.Float64)
    if variant == "buy_hold":
        return df.with_columns(pl.lit(1.0).alias("weight"))
    if variant == "defense":
        # 基本防守：任一触发 → 0.3
        return df.with_columns((1.0 - 0.7 * defense).alias("weight"))
    if variant == "defense_hike_single":
        # 对照：defense ∪ hike 任一触发 → 0.3，无双触发空仓（隔离加息腿独立贡献）
        return df.with_columns((1.0 - 0.7 * pl.max_horizontal(defense, hike)).alias("weight"))
    if variant == "defense_double":
        # 对照：defense 内部双触发（scissors<0 且 DOI≥70）→ 0，单触发 → 0.3
        return df.with_columns(
            (
                1.0
                - 0.7 * defense
                - 0.3 * (defense * (pl.col("scissors") < 0.0) * (pl.col("doi") >= _DOI_TH))
            ).alias("weight")
        )
    if variant == "defense_ffr":
        # defense × 加息腿：任一触发→0.3、双触发→0
        return df.with_columns(
            (1.0 - 0.7 * pl.max_horizontal(defense, hike) - 0.3 * (defense * hike)).alias("weight")
        )
    if variant == "offense_def":
        return df.with_columns(((0.3 + 0.7 * offense) * (1.0 - 0.7 * defense)).alias("weight"))
    if variant == "offense_def_double":
        # 对照：进攻脚 ×（defense 内部双触发空仓）
        dbl = (
            1.0
            - 0.7 * defense
            - 0.3 * (defense * (pl.col("scissors") < 0.0) * (pl.col("doi") >= _DOI_TH))
        )
        return df.with_columns(((0.3 + 0.7 * offense) * dbl).alias("weight"))
    if variant == "offense_def_ffr":
        # offense ×（defense + 加息腿）
        dh = 1.0 - 0.7 * pl.max_horizontal(defense, hike) - 0.3 * (defense * hike)
        return df.with_columns(((0.3 + 0.7 * offense) * dh).alias("weight"))
    # offense_defcrowd_ffr：offense ×（defense_crowd × 加息腿）
    # 三腿组合：无触发→1.0、任一触发→0.3、双触发及以上→0
    any_on = pl.max_horizontal(defense, crowd, hike)
    multi_on = pl.max_horizontal(defense * crowd, defense * hike, crowd * hike)
    dc = 1.0 - 0.7 * any_on - 0.3 * multi_on
    return df.with_columns(((0.3 + 0.7 * offense) * dc).alias("weight"))


def _nav(df: pl.DataFrame) -> pl.DataFrame:
    """T+1 生效：当日 weight → 次日仓位，复利净值。"""
    w = df["weight"].shift(1).fill_null(1.0)
    return df.with_columns((1.0 + w * df["ret"].fill_null(0.0)).cum_prod().alias("nav"))


def _metrics(nav: pl.Series) -> dict[str, float]:
    """CAGR / MaxDD / Sharpe（年化 252，无风险 0，对齐既有脚本口径）。"""
    arr = [v if v > 0 else 1e-9 for v in nav.to_list()]
    if len(arr) < 2:
        return {"cagr": 0.0, "max_dd": 0.0, "sharpe": 0.0}
    n = len(arr)
    years = max(n / 252.0, 1e-9)
    cagr = ((arr[-1] / arr[0]) ** (1.0 / years) - 1.0) * 100.0 if arr[0] > 0 else 0.0
    peak, max_dd = -1e9, 0.0
    for v in arr:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    rets = [arr[i] / arr[i - 1] - 1.0 for i in range(1, len(arr)) if arr[i - 1] > 0]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var = sum((r - mean_r) ** 2 for r in rets) / max(len(rets) - 1, 1) if len(rets) > 1 else 0.0
    sharpe = mean_r / math.sqrt(var) * math.sqrt(252) if var > 0 else 0.0
    return {"cagr": cagr, "max_dd": max_dd * 100.0, "sharpe": sharpe}


def _ic_table(df: pl.DataFrame) -> list[str]:
    """加息特征对 270100 fwd20/fwd60 的 IC（全周期/样本外）+ 条件收益。"""
    d = df.with_columns(
        pl.col("close").pct_change(20).shift(-20).alias("fwd20"),
        pl.col("close").pct_change(60).shift(-60).alias("fwd60"),
    )
    rows = []
    for col, label in [
        ("ffr6m", "原始 pp"),
    ]:
        sub = d.select([col, "fwd20", "fwd60"]).drop_nulls()
        oos = d.filter(pl.col("trade_date") >= _OOS).select([col, "fwd20", "fwd60"]).drop_nulls()
        r20, _ = stats.spearmanr(sub[col], sub["fwd20"])
        r60, p60 = stats.spearmanr(sub[col], sub["fwd60"])
        r20o, _ = stats.spearmanr(oos[col], oos["fwd20"])
        r60o, p60o = stats.spearmanr(oos[col], oos["fwd60"])
        rows.append(
            f"| {label} | {r20:+.3f} | {r60:+.3f} (p={p60:.1e}) | {r20o:+.3f} | {r60o:+.3f} (p={p60o:.1e}) | {len(sub)} |"
        )
    # 条件收益：加息期（ffr6m>=0.25pp）vs 非加息期
    hi = d.filter(pl.col("ffr6m") >= _HIKE_TH)["fwd60"].drop_nulls()
    lo = d.filter(pl.col("ffr6m") < _HIKE_TH)["fwd60"].drop_nulls()
    rows.append(
        f"**条件收益 fwd60**：加息期中位 {hi.median():+.2%} / 上涨率 {(hi > 0).mean():.0%} "
        f"(n={len(hi)}) vs 非加息期中位 {lo.median():+.2%} / 上涨率 {(lo > 0).mean():.0%} (n={len(lo)})"
    )
    return rows


def main() -> None:
    df = _load()
    print(f"面板: {df['trade_date'].min()} ~ {df['trade_date'].max()}, {len(df)} 日")

    # 1) IC 与条件收益
    ic_rows = _ic_table(df)

    # 2) 变体回测
    results: list[dict[str, object]] = []
    for variant in _VARIANTS:
        wdf = _weights(df, variant)
        nav = _nav(wdf)
        full = _metrics(nav["nav"])
        oos = _metrics(nav.filter(pl.col("trade_date") >= _OOS)["nav"])
        # 加息腿触发统计（仅 ffr 变体）
        hike_days = int((wdf["ffr6m"] >= _HIKE_TH).sum())
        results.append(
            {
                "variant": variant,
                "加息触发天数": hike_days,
                "全CAGR%": round(full["cagr"], 2),
                "全MaxDD%": round(full["max_dd"], 2),
                "全Sharpe": round(full["sharpe"], 3),
                "外CAGR%": round(oos["cagr"], 2),
                "外MaxDD%": round(oos["max_dd"], 2),
                "外Sharpe": round(oos["sharpe"], 3),
            }
        )
    res = pl.DataFrame(results)

    # 3) 正交性：defense 与 hike 触发重叠
    wdf = _weights(df, "defense_ffr")
    defense_on = (wdf["scissors"] < 0.0) | (wdf["doi"] >= _DOI_TH)
    hike_on = wdf["ffr6m"] >= _HIKE_TH
    both = (defense_on & hike_on).sum()
    overlap_pct = both / max(int(hike_on.sum()), 1) * 100.0
    ortho = f"正交性：defense 触发 {int(defense_on.sum())} 天 / hike 触发 {int(hike_on.sum())} 天 / 同时触发 {int(both)} 天（占 hike 触发 {overlap_pct:.0f}%）"

    # 4) 落盘
    _OUT.mkdir(parents=True, exist_ok=True)
    res.write_csv(_OUT / "semi_ffr_defense_leg.csv")

    lines = [
        "# 加息腿接入半导体深研线（270100）独立防守腿研究",
        "",
        "> 口径：2018-01 起全周期 / 2022-01 起样本外，T+1 次日生效、无前视、无摩擦；",
        "> 加息腿 = FRED FEDFUNDS 月频 diff(6)（pp）asof 对齐日频，阈值 ≥0.25pp（沿用方向池 guarded_hike 参数）。",
        "",
        "## 1. 加息特征 IC 与条件收益（270100）",
        "",
        "| 口径 | fwd20 全IC | fwd60 全IC | fwd20 外IC | fwd60 外IC | n |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in ic_rows:
        if r.startswith("|"):
            parts = r.split("|")
            lines.append(
                f"| {parts[1]} | {parts[2]} | {parts[3]} | {parts[4]} | {parts[5]} | {parts[6]} |"
            )
        else:
            lines.append("")
            lines.append(r)
            lines.append("")
    lines += [
        "",
        "## 2. 变体回测对比（全周期 / 样本外）",
        "",
        "| 变体 | 说明 | 加息触发天数 | 全CAGR% | 全MaxDD% | 全Sharpe | 外CAGR% | 外MaxDD% | 外Sharpe |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    labels = {
        "buy_hold": "买入持有（基准）",
        "defense": "基本防守（scissors<0/DOI≥70 任一→0.3）",
        "defense_hike_single": "对照：defense∪hike 任一→0.3（无空仓规则）",
        "defense_double": "对照：defense 内部双触发→0（无加息腿）",
        "defense_ffr": "防守+加息腿（任一→0.3、双触发→0）",
        "offense_def": "进攻脚×基本防守",
        "offense_def_double": "对照：进攻×defense 内部双触发→0",
        "offense_def_ffr": "进攻×防守+加息腿",
        "offense_defcrowd_ffr": "进攻×防守×crowd×加息（四层）",
    }
    for r in res.iter_rows(named=True):
        lines.append(
            f"| {r['variant']} | {labels[r['variant']]} | {r['加息触发天数']} | {r['全CAGR%']} | "
            f"{r['全MaxDD%']} | {r['全Sharpe']} | {r['外CAGR%']} | {r['外MaxDD%']} | {r['外Sharpe']} |"
        )
    lines += ["", f"> {ortho}", ""]
    lines += [
        "## 3. 结论",
        "",
        "- 待运行时由实证填写：加息腿与既有防守门是否正交、样本外增量方向与量级、定位建议。",
    ]
    (_OUT / "semi_ffr_defense_leg.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(res)
    print("\n" + ortho)
    print(f"\n写入 {_OUT / 'semi_ffr_defense_leg.csv'} / .md")


if __name__ == "__main__":
    main()
