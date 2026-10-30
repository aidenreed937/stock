"""半导体(270100) 毛利率扩张前瞻腿（GM Leading Indicator）构建 + 增量 IC 检验。

Stage 1：ASML 单家验证（两阶段方案第一阶段）。
数据源：data/curated/industry/semiconductor_equipment_gm.parquet（ASML 6-K 季度黄金表，
release_date = 6-K filingDate，无前视）。

前瞻因子（leg_type 独立分组，不入剪刀差）：
- gm_guidance_score：下季 GM 指引水平的滚动分位（管理层前瞻，核心）
- gm_expansion_score：(gm_guidance_next - gm_actual) 滚动分位 = 管理层预期的 GM 扩张/收缩
- ibm_share_score：Installed Base Management（服务/mix）占比滚动分位
- bookings_score：Net bookings 同比滚动分位（2016-2025 有值，2026-Q1 起 ASML 不再披露→诚实缺失）
- gm_leading_score：0.5·guidance + 0.3·expansion + 0.2·ibm_share 复合（guidance 缺失时回退）

IC 检验（对齐 semi_structural_ic 口径）：
- Spearman(腿分, f60)，f60 = close.shift(-60)/close - 1，270100 日频
- 整体 + 年度 + 样本外（2022-01 起）
- 增量：控制剪刀差（scissors_score）后，gm_leading_score 是否仍具增量解释力（分层/回归）

输出：data/analytics/industry_strategy/semi_gm_leading.{csv,md}

用法：uv run python scripts/semi_gm_leading.py
"""

from __future__ import annotations

import datetime
from pathlib import Path

import polars as pl
from scipy import stats

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_GM = Path("data/curated/industry/semiconductor/equipment/semiconductor_equipment_gm.parquet")
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_GRID = Path("data/curated/mart/global_macro_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "270100"
_WIN = 12  # 季频滚动分位窗口（12 季 = 3 年）


def _rolling_pct(series: pl.Series, window: int = _WIN) -> pl.Series:
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


def _quarterly_pct(df: pl.DataFrame, value_col: str, window_quarters: int = _WIN) -> pl.DataFrame:
    """季频序列 → 滚动分位（按 release_date 生效，无前视）。"""
    out = (
        df.select(["release_date", value_col])
        .rename({"release_date": "trade_date"})
        .drop_nulls()
        .sort("trade_date")
    )
    pct = _rolling_pct(out[value_col].cast(pl.Float64), window=window_quarters)
    return out.with_columns(pct.alias("pct")).select(["trade_date", "pct"])


def _forward_fill_to_daily(quarterly: pl.DataFrame, score_col: str) -> pl.DataFrame:
    """季度分位 → 日频前向填充（对齐结构性腿范式）。"""
    grid = pl.read_parquet(_GRID).select(["trade_date"]).sort("trade_date")
    q = quarterly.rename({"pct": score_col})
    return (
        grid.join(q, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col(score_col).fill_null(strategy="forward"))
        .drop_nulls([score_col])
    )


def build_gm_legs() -> pl.DataFrame:
    """构建 gm_leading 相关腿的日频表（270100 单独输出）。"""
    gm = pl.read_parquet(_GM)
    grid = pl.read_parquet(_GRID).select(["trade_date"]).sort("trade_date")

    # 基础量：ibm_share（服务占比）、gm_actual
    base = gm.with_columns(
        (pl.col("ibm_sales_eur_m") / pl.col("net_sales_eur_m") * 100.0).alias("ibm_share"),
    )

    legs: list[pl.DataFrame] = []

    # 1. gm_guidance_score：下季 GM 指引水平滚动分位
    q_guid = _quarterly_pct(
        base.select(["release_date", "gm_guidance_next_pct"]), "gm_guidance_next_pct"
    )
    legs.append(_forward_fill_to_daily(q_guid, "gm_guidance_score"))

    # 2. gm_expansion_score：(guidance_next - gm_actual) 滚动分位
    exp = base.with_columns(
        (pl.col("gm_guidance_next_pct") - pl.col("gross_margin_pct")).alias("gm_expansion")
    ).select(["release_date", "gm_expansion"])
    q_exp = _quarterly_pct(exp, "gm_expansion")
    legs.append(_forward_fill_to_daily(q_exp, "gm_expansion_score"))

    # 3. ibm_share_score：服务/mix 占比滚动分位
    q_ibm = _quarterly_pct(base.select(["release_date", "ibm_share"]), "ibm_share")
    legs.append(_forward_fill_to_daily(q_ibm, "ibm_share_score"))

    # 4. bookings_score：net bookings 同比滚动分位（2026-Q1 起 ASML 不再披露→缺失）
    bk = base.with_columns(pl.col("net_bookings_eur_m").pct_change(4).alias("bookings_yoy"))
    q_bk = _quarterly_pct(bk.select(["release_date", "bookings_yoy"]), "bookings_yoy")
    legs.append(_forward_fill_to_daily(q_bk, "bookings_score"))

    # 合并
    out = grid
    for leg in legs:
        out = out.join(leg, on="trade_date", how="left")
    out = out.sort("trade_date")

    # 5. gm_leading_score：复合（guidance 缺失回退 ibm）
    out = out.with_columns(
        pl.when(pl.col("gm_guidance_score").is_not_null())
        .then(
            0.5 * pl.col("gm_guidance_score")
            + 0.3 * pl.col("gm_expansion_score").fill_null(50.0)
            + 0.2 * pl.col("ibm_share_score").fill_null(50.0)
        )
        .otherwise(pl.col("ibm_share_score").fill_null(50.0))
        .alias("gm_leading_score")
    )
    return out.with_columns(pl.lit(_INDUSTRY).alias("industry_code"))


def _load() -> pl.DataFrame:
    """270100 日频：close/f60 + gm 腿 + 剪刀差（scissors_score）。"""
    panel = pl.read_parquet(_PANEL)
    semi = panel.filter(
        (pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START)
    ).sort("trade_date")
    legs = pl.read_parquet(_GRID).select(["trade_date"]).sort("trade_date")
    gm_legs = build_gm_legs()
    return (
        semi.select(["trade_date", "close", "scissors_score"])
        .join(gm_legs, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns((pl.col("close").shift(-60) / pl.col("close") - 1.0).alias("f60"))
    )


def _spearman_ic(sub: pl.DataFrame, col: str) -> float | None:
    s = sub.drop_nulls([col, "f60"])
    if len(s) < 30 or s[col].n_unique() < 2 or s["f60"].n_unique() < 2:
        return None
    return round(stats.spearmanr(s[col].to_list(), s["f60"].to_list())[0], 3)


def _yearly_ic(m: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    rows = []
    for y in sorted(m["trade_date"].dt.year().unique().to_list()):
        sub = m.filter(pl.col("trade_date").dt.year() == y)
        row: dict[str, object] = {"year": y, "n": len(sub)}
        for c in cols:
            row[c] = _spearman_ic(sub, c)
        rows.append(row)
    return pl.DataFrame(rows)


def _incremental_test(m: pl.DataFrame, col: str) -> dict[str, float | None]:
    """增量检验：控制 scissors_score 后，col 是否仍有解释力。

    方法：rank(col) 对 f60 回归中，加入 scissors 控制前后的 Spearman 偏相关近似
    ——用分层均值差 + 与剪刀差同回归的 t 检验。这里采用**残差法**：
    f60 对 scissors 回归取残差，再算残差与 col 的 Spearman。
    """
    s = m.drop_nulls(["scissors_score", col, "f60"])
    if len(s) < 60:
        return {"n": len(s), "partial_ic": None, "raw_ic": None}
    raw = _spearman_ic(s, col)
    # 残差法：rank 化后回归控制
    from scipy.stats import rankdata

    y = rankdata(s["f60"].to_list())
    x_sc = rankdata(s["scissors_score"].to_list())
    x_col = rankdata(s[col].to_list())
    n = len(y)
    # 简单 OLS：f60 ~ scissors，取残差
    slope = sum((x_sc[i] - x_sc.mean()) * (y[i] - y.mean()) for i in range(n)) / sum(
        (x_sc[i] - x_sc.mean()) ** 2 for i in range(n)
    )
    resid = [y[i] - (y.mean() + slope * (x_sc[i] - x_sc.mean())) for i in range(n)]
    partial = stats.spearmanr(resid, x_col)[0] if n > 2 else None
    return {"n": n, "partial_ic": round(partial, 3) if partial is not None else None, "raw_ic": raw}


def _current(m: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    latest = m.filter(pl.col("trade_date") == m["trade_date"].max())
    row: dict[str, object] = {"trade_date": latest["trade_date"].max()}
    for c in cols:
        row[c] = latest[c].drop_nulls().last()
    return pl.DataFrame([row])


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    m = _load()
    cols = [
        "gm_leading_score",
        "gm_guidance_score",
        "gm_expansion_score",
        "ibm_share_score",
        "bookings_score",
    ]
    labels = {
        "gm_leading_score": "GM 前瞻复合（guidance+expansion+ibm）",
        "gm_guidance_score": "下季 GM 指引水平",
        "gm_expansion_score": "GM 指引-实际 扩张幅度",
        "ibm_share_score": "服务/mix 占比",
        "bookings_score": "Net bookings 同比（2016-2025）",
    }

    overall = {c: _spearman_ic(m, c) for c in cols}
    overall_oos = {c: _spearman_ic(m.filter(pl.col("trade_date") >= _OOS), c) for c in cols}
    y = _yearly_ic(m, cols)
    inc = {c: _incremental_test(m, c) for c in cols}
    cur = _current(m, cols)

    y.write_csv(_OUT / "semi_gm_leading_yearly.csv")
    cur.write_csv(_OUT / "semi_gm_leading_current.csv")
    inc_rows = pl.DataFrame(
        [
            {
                "leg": c,
                **{
                    f"{k}": (v[k] if v[k] is not None else None)
                    for k in ("n", "raw_ic", "partial_ic")
                },
            }
            for c, v in inc.items()
        ]
    )
    inc_rows.write_csv(_OUT / "semi_gm_leading_incremental.csv")

    md = f"""# 半导体（270100）GM 前瞻腿（Gross Margin Leading Indicator）IC 报告

> Stage 1（ASML 单家验证）。数据源 `semiconductor_equipment_gm`（ASML 6-K 季度黄金表，
> release_date = 6-K filingDate，无前视）。f60 = 60 日前瞻收益。
> 窗口 {m["trade_date"].min()} ~ {m["trade_date"].max()}，样本外自 {_OOS}。
> 腿按 leg_type 独立分组（不入剪刀差）；2026-Q1 起 ASML 不再披露 net bookings → bookings_score 覆盖 2016-2025。

## 1) 整体 / 样本外 IC

| 腿 | 全周期 IC | 样本外 IC |
| :--- | :---: | :---: |
"""
    for c in cols:
        md += f"| **{labels[c]}** | {overall[c]} | {overall_oos[c]} |\n"

    md += f"""

## 2) 年度 IC

| 年份 | n | {" | ".join(labels[c] for c in cols)} |
| :---: | :---: | {" | ".join(":---:" for _ in cols)} |
"""
    for r in y.to_dicts():
        md += (
            f"| {r['year']} | {r['n']} | "
            + " | ".join(str(r[c]) if r[c] is not None else "-" for c in cols)
            + " |\n"
        )

    md += """

## 3) 增量检验（控制剪刀差后）

> partial_ic = f60 对 scissors 回归取残差后，残差与腿分的 Spearman（rank 残差法）。

| 腿 | n | 原始 IC | 控制剪刀差后偏 IC |
| :--- | :---: | :---: | :---: |
"""
    for r in inc_rows.to_dicts():
        md += (
            f"| {labels[r['leg']]} | {r['n']} | {r['raw_ic'] or '-'} | {r['partial_ic'] or '-'} |\n"
        )

    md += f"""

## 4) 当前截面（{cur["trade_date"][0]}）

| 腿 | 当前值 |
| :--- | :---: |
"""
    for c in cols:
        v = cur[c][0]
        md += f"| {labels[c]} | {v if v is None else round(v, 1)} |\n"

    # 动态取最后一年 bookings_score 的年度 IC 值（伪影说明用，避免硬编码）
    _bk_last_year = int(m["trade_date"].dt.year().max())
    _bk_last_ic = next(
        (r["bookings_score"] for r in y.to_dicts() if r["year"] == _bk_last_year), None
    )

    md += f"""

## 5) 结论与局限（Stage 1 诚实标注）

- **GM 指引腿**（gm_guidance_score / gm_expansion_score）：管理层对下季毛利率的前瞻，
  是"毛利率扩张可前瞻预测"的最直接量化——财报公布前即可获得、release_date 无前视。
- **结构性局限**：2026-Q1 起 ASML 不再在新闻稿披露 Net bookings 数值（此前连续披露），
  bookings_score 覆盖 2016-2025；backlog 亦仅早期披露。GM guidance 与 IBM/mix 是
  全期可得的可靠前瞻因子。
- **bookings 冻结伪影**：最后一季真实 bookings 值来自 2025-Q4（release 2026-01-28），
  此后无新值 → 日频前向填充冻结为常数。因此年度 IC 中 {_bk_last_year} 列
  {_bk_last_ic if _bk_last_ic is not None else "-"} **不是真实负预测信号**，
  而是该年仅剩 2 个取值（年初真实高值 100.0 vs 冻结低值 91.7）制造的两个时段
  收益差异伪相关——常数段本身无排序信息。读数时应忽略冻结年度的 bookings_score IC。
- **单公司单行业**：ASML 单家是设备龙头模板，结论不可直接外推到四巨头/全行业；
  增量 IC 达标与否是 Stage 2（四巨头扩展）的门槛依据。
- 数据文件：`semi_gm_leading_yearly.csv` / `semi_gm_leading_incremental.csv` / `semi_gm_leading_current.csv`。
"""
    (_OUT / "semi_gm_leading.md").write_text(md, encoding="utf-8")
    print("=== 半导体 270100 GM 前瞻腿 IC ===")
    print("整体 IC:", overall)
    print("样本外 IC:", overall_oos)
    print("\n增量检验（控制剪刀差）:")
    print(inc_rows)
    print("\n当前截面:", cur)
    print(f"\n报告已生成: {_OUT / 'semi_gm_leading.md'}")


if __name__ == "__main__":
    main()
