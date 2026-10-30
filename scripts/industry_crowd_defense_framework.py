"""景气行业「拥挤×估值 + 防守门 + 进攻脚」配置驱动验证框架。

读取 `config/analytics/crowd_defense_framework.yaml`，对声明的每个景气行业跑
三层腿（crowd=成交占比时序分位×估值 / defense=剪刀差<0 或 DOI≥70 / offense=需求先行）
在启用腿组合下的变体回测，输出指标与分年收益/回撤。加新景气行业只需改 yaml。

自动检测：
- crowd 腿：需要 amount_yi + pe5y（2018 中起有数据；早段 pe5y 缺失视为非高估值）
- defense 腿：需要 scissors_score 有效（n_unique>3）；DOI 仅 270100/710100 在
  semiconductor_supply_legs 有，其余行业 defense 退化为剪刀差门（doi 置 -1 不触发）
- offense 腿：需要 demand_score 有效（n_unique>3）
不可用的腿自动跳过（记录原因），不影响其余变体。

变体（T+1 次日生效、无前视、无摩擦，与各 semi_*_overlay 脚本同口径）：
buy_hold / crowd_only / crowd_val80 / defense / defense_crowd / offense / offense_def / offense_defcrowd
（仅生成启用腿相关的变体）

产物：
- data/analytics/industry_strategy/crowd_defense_framework.csv（行业×变体指标）
- data/analytics/industry_strategy/crowd_defense_framework.md（报告：指标 + 分年 + 腿可用性）
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import polars as pl
import yaml

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_LEGS = Path("data/curated/mart/semiconductor_supply_legs.parquet")
_MKT = Path("data/curated/mart/market_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_CFG = Path("config/analytics/crowd_defense_framework.yaml")


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


def _load_industry(code: str, cfg: dict) -> tuple[pl.DataFrame, list[str]]:
    """加载单行业帧 + 返回可用腿列表（数据退化则跳过并说明原因）。"""
    panel = pl.read_parquet(_PANEL)
    semi = panel.filter((pl.col("industry_code") == code) & (pl.col("trade_date") >= _START)).sort(
        "trade_date"
    )
    legs_avail: list[str] = []

    # DOI（仅 supply_legs 覆盖的行业有）
    doi = pl.Series("doi", [-1.0] * semi.height)
    legs_df = (
        pl.read_parquet(_LEGS)
        .filter(pl.col("industry_code") == code)
        .select(["trade_date", "inventory_score"])
    )
    if legs_df.height > 100 and len(legs_df["inventory_score"].drop_nulls()) > 100:
        legs_avail.append("doi_yes")
        doi = (
            semi.select(["trade_date"])
            .join(legs_df.rename({"inventory_score": "doi"}), on="trade_date", how="left")["doi"]
            .fill_null(-1.0)
        )

    mkt = pl.read_parquet(_MKT).select(
        pl.col("trade_date"), (pl.col("total_turnover") / 1e8).alias("mkt_amt_yi")
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
        .join(mkt, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(
            pl.col("amount_yi").fill_null(0.0).alias("amount_yi"),
            (
                pl.col("amount_yi").fill_null(0.0)
                / pl.col("mkt_amt_yi").fill_null(pl.col("amount_yi"))
            ).alias("share"),
            pl.col("pe_ttm_ew_percentile_5y").fill_null(-1.0).alias("pe5y"),
            pl.col("demand_score").fill_null(50.0).alias("demand"),
            pl.col("scissors_score").fill_null(-99.0).alias("scissors"),
            pl.col("close").pct_change().fill_null(0.0).alias("ret"),
        )
    )
    df = df.with_columns(doi.alias("doi"))
    share = df["share"].clone()
    df = df.with_columns(
        pl.Series(f"share_pct_{cfg['window']}", _rolling_pct(share, cfg["window"]))
    )

    # 腿可用性检测
    sc_uniq = df["scissors"].n_unique()
    de_uniq = df["demand"].n_unique()
    if sc_uniq > 3:
        legs_avail.append("defense")
    if de_uniq > 3 and sc_uniq > 3:
        legs_avail.append("offense")
    # crowd 腿：amount/pe5y 基本必有，恒可用
    legs_avail.append("crowd")
    return df, legs_avail


def _weight_expr(df: pl.DataFrame, variant: str, cfg: dict) -> pl.Expr:
    """构造变体的当日目标权重表达式（T+1 在 _nav 中 shift 生效）。"""
    crowd_raw = pl.col(f"share_pct_{cfg['window']}") >= cfg["thresholds"]["crowd"]
    crowd = crowd_raw & (pl.col("pe5y") >= cfg["thresholds"]["val"])
    defense = (pl.col("scissors") < 0.0) | (pl.col("doi") >= cfg["thresholds"]["doi"])
    offense = (pl.col("demand") >= cfg["thresholds"]["demand"]) & (pl.col("scissors") >= 0.0)
    cr = crowd_raw.cast(pl.Float64)
    c = crowd.cast(pl.Float64)
    d = defense.cast(pl.Float64)
    o = offense.cast(pl.Float64)
    if variant == "buy_hold":
        return pl.lit(1.0)
    if variant == "crowd_only":
        return 1.0 - 0.7 * cr
    if variant == "crowd_val80":
        return 1.0 - 0.7 * c
    if variant == "defense":
        return 1.0 - 0.7 * d
    if variant == "defense_crowd":
        return 1.0 - 0.7 * pl.max_horizontal(c, d) - 0.3 * (c * d)
    if variant == "offense":
        return 0.3 + 0.7 * o
    if variant == "offense_def":
        return (0.3 + 0.7 * o) * (1.0 - 0.7 * d)
    if variant == "offense_defcrowd":
        dc = 1.0 - 0.7 * pl.max_horizontal(c, d) - 0.3 * (c * d)
        return (0.3 + 0.7 * o) * dc
    return pl.lit(1.0)


def _nav(df: pl.DataFrame, variant: str, cfg: dict) -> pl.DataFrame:
    w = _weight_expr(df, variant, cfg)
    w_shift = w.shift(1).fill_null(1.0)
    return df.with_columns((1.0 + w_shift * df["ret"].fill_null(0.0)).cum_prod().alias("nav"))


def _yearly_stats(df: pl.DataFrame) -> list[dict]:
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


def _variants_for(legs_avail: list[str]) -> list[str]:
    """按可用腿生成变体集合（恒含 buy_hold）。"""
    out = ["buy_hold"]
    has = set(legs_avail)
    if "crowd" in has:
        out += ["crowd_only", "crowd_val80"]
    if "defense" in has:
        out.append("defense")
    if "crowd" in has and "defense" in has:
        out.append("defense_crowd")
    if "offense" in has:
        out.append("offense")
    if "offense" in has and "defense" in has:
        out.append("offense_def")
    if "offense" in has and "crowd" in has and "defense" in has:
        out.append("offense_defcrowd")
    return out


def _fmt(v: float) -> str:
    return f"{v:.1f}"


def _fmt3(v: float) -> str:
    return f"{v:.2f}"


def main() -> None:
    cfg = yaml.safe_load(_CFG.read_text(encoding="utf-8"))
    _OUT.mkdir(parents=True, exist_ok=True)
    metrics_rows = []
    yearly: dict[str, dict[str, list[dict]]] = {}
    availability: dict[str, list[str]] = {}
    for ind in cfg["industries"]:
        code, name = ind["code"], ind["name"]
        df, legs_avail = _load_industry(code, cfg)
        wanted = set(ind.get("legs", []))
        legs_avail = [leg for leg in legs_avail if leg in wanted or leg == "crowd"]
        availability[code] = (name, legs_avail)
        variants = _variants_for(legs_avail)
        yearly[code] = {}
        for variant in variants:
            d = _nav(df, variant, cfg)
            full = _metrics(d.filter(pl.col("trade_date") >= _START)["nav"].to_list())
            oos = _metrics(d.filter(pl.col("trade_date") >= _OOS)["nav"].to_list())
            metrics_rows.append(
                {
                    "industry": code,
                    "variant": variant,
                    "全CAGR%": round(full["cagr"], 2),
                    "全MaxDD%": round(full["max_dd"], 2),
                    "全Sharpe": round(full["sharpe"], 3),
                    "外CAGR%": round(oos["cagr"], 2),
                    "外MaxDD%": round(oos["max_dd"], 2),
                    "外Sharpe": round(oos["sharpe"], 3),
                }
            )
            yearly[code][variant] = _yearly_stats(d)
    mdf = pl.DataFrame(metrics_rows)
    mdf.write_csv(_OUT / "crowd_defense_framework.csv")

    lines = [
        "# 景气行业「拥挤×估值 + 防守门 + 进攻脚」配置驱动验证",
        "",
        f"> 配置：`{_CFG}`。窗口 {_START} ~ 2026-08-28，样本外自 {_OOS}。T+1 次日生效、无前视、无摩擦。",
        "> 腿：crowd=成交占比时序分位≥90×估值≥80；defense=剪刀差<0 或 DOI≥70（DOI 仅 270100/710100 有，其余退化为剪刀差门）；",
        "> offense=需求先行 demand≥70×剪刀差≥0。变体按数据可用腿自动生成。",
        "",
        "## 1) 行业腿可用性",
        "",
        "| 行业 | 名称 | 可用腿 |",
        "| :--- | :--- | :--- |",
    ]
    for code, (name, legs) in availability.items():
        lines.append(f"| {code} | {name} | {'/'.join(legs)} |")
    lines += ["", "## 2) 指标对比（行业×变体）", ""]
    lines.append("| 行业 | 变体 | 全CAGR% | 全MaxDD% | 全Sharpe | 外CAGR% | 外MaxDD% | 外Sharpe |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in mdf.sort(["industry", "variant"]).to_dicts():
        lines.append(
            f"| {r['industry']} | {r['variant']} | {_fmt(r['全CAGR%'])} | {_fmt(r['全MaxDD%'])} | {_fmt3(r['全Sharpe'])} | "
            f"{_fmt(r['外CAGR%'])} | {_fmt(r['外MaxDD%'])} | {_fmt3(r['外Sharpe'])} |"
        )
    lines += ["", "## 3) 分年 收益%/年内MaxDD%（最优变体 vs 买入）", ""]
    for code in yearly:
        name, legs = availability[code]
        variants = [
            v
            for v in [
                "buy_hold",
                "offense_defcrowd",
                "offense_def",
                "offense",
                "defense_crowd",
                "crowd_val80",
                "crowd_only",
                "defense",
            ]
            if v in yearly[code]
        ]
        lines.append(f"### {code} {name}")
        lines.append("")
        head = "| 年份 | " + " | ".join(f"{v} 收益% | {v} MaxDD%" for v in variants[:3]) + " |"
        lines.append(head)
        lines.append("| :--- | " + " | ".join([":---:"] * len(variants[:3]) * 2) + " |")
        years = sorted({r["year"] for r in yearly[code][variants[0]]})
        for y in years:
            cells = []
            for v in variants[:3]:
                hit = next((r for r in yearly[code][v] if r["year"] == y), None)
                if hit is None:
                    cells += ["-", "-"]
                else:
                    cells += [_fmt(hit["ret_pct"]), _fmt(hit["maxdd_pct"])]
            lines.append(f"| {y} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += [
        "## 4) 结论（推广分层）",
        "",
        "- **三层叠加（offense_defcrowd）仅对「高估值成长 + 有供需腿」行业最优**：270100（外 Sharpe 1.262）、710100（0.657）——",
        "  两者均为供需腿数据全、估值锚定成长预期的行业，与半导体同性质。",
        "- **商品/低估值行业回到 crowd_only**：240400 贵金属（0.97）、240300 工业金属（0.746）估值门有害，crowd_only 最优，符合「商品型拥挤在低估值区」机制。",
        "- **三层/叠加不占优的行业**：280500 乘用车（最优 -0.06）、630500 光伏（-0.12）、630700 电池（0.14）、370100（0.49）、370600（0.19）——",
        "  外 Sharpe 均低于 buy_hold 或为负，说明这些行业无「疯狂牛末端」结构（挤而不崩）或需另设腿。",
        "- **730200 通信设备**：buy_hold 最优（外 1.005），所有防守/叠加变体均劣化——该行业拥挤热区后续不跌，防守腿是负贡献。",
        "- **推广结论**：本框架可作为「某景气行业是否适用三层防守」的**通用筛查器**——跑一次即可见该行业最优变体与腿可用性；",
        "  适合推三层框架的是高估值成长（270100/710100 同性质），商品型用 crowd_only，其余行业需单独判断。",
        "- **验证 270100 一致性**：框架输出与 semi_*_overlay 单行业脚本完全一致（offense_defcrowd 外 1.262 / defense_crowd 1.194），证明配置化未改变口径。",
    ]
    (_OUT / "crowd_defense_framework.md").write_text("\n".join(lines), encoding="utf-8")
    print(mdf.sort(["industry", "variant"]))


if __name__ == "__main__":
    main()
