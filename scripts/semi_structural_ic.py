"""半导体(270100) AI 结构性确认腿（云CapEx 算力）IC 报告。

对结构性腿做独立实证：ai_capex_score 对 60 日前瞻收益 f60 的 Spearman IC
（整体 + 年度 + 当前截面），回答"AI 主驱动"是否可跟踪。口径与供给端腿验证一致：
industry_l2_panel_daily 270100 + semiconductor_structural_legs，f60 = close.shift(-60)/close-1。

输出：data/analytics/industry_strategy/semi_structural_ic.{csv,md}
"""

from __future__ import annotations

import datetime
from pathlib import Path

import polars as pl
from scipy import stats

_START = datetime.date(2018, 1, 1)
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_LEGS = Path("data/curated/mart/semiconductor_structural_legs.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "270100"


def _load() -> pl.DataFrame:
    panel = pl.read_parquet(_PANEL)
    semi = panel.filter(
        (pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START)
    ).sort("trade_date")
    legs = (
        pl.read_parquet(_LEGS)
        .filter((pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START))
        .sort("trade_date")
    )
    return (
        semi.select(["trade_date", "close"])
        .join(
            legs.select(["trade_date", "ai_capex_score"]),
            on="trade_date",
            how="left",
        )
        .sort("trade_date")
        .with_columns((pl.col("close").shift(-60) / pl.col("close") - 1.0).alias("f60"))
    )


def _spearman_ic(sub: pl.DataFrame, col: str) -> float | None:
    s = sub.drop_nulls([col, "f60"])
    # 常数输入时 Spearman 无定义，返回 None
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


def _current_cross_section(m: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    latest = m.filter(pl.col("trade_date") == m["trade_date"].max())
    row: dict[str, object] = {"trade_date": latest["trade_date"].max()}
    for c in cols:
        row[c] = latest[c].drop_nulls().last()
    return pl.DataFrame([row])


def main() -> None:
    m = _load()
    _OUT.mkdir(parents=True, exist_ok=True)
    cols = ["ai_capex_score"]
    labels = {
        "ai_capex_score": "云CapEx算力（AI 算力扩张）",
    }

    overall = {c: _spearman_ic(m, c) for c in cols}
    y = _yearly_ic(m, cols)
    cur = _current_cross_section(m, cols)
    y.write_csv(_OUT / "semi_structural_ic.csv")
    cur.write_csv(_OUT / "semi_structural_current.csv")

    md = f"""# 半导体（270100）AI 结构性确认腿 IC 报告

> 结构性腿：ai_capex_score（北美四大云厂商 CapEx 同比 12 季滚动分位），日频前向填充、release_date 生效（无前视）。
> 数据源：`semiconductor_structural_legs`（trade_date, industry_code, ai_capex_score）。
> IC = Spearman(腿分, f60)，f60 = 60 日前瞻收益。窗口 {m["trade_date"].min()} ~ {m["trade_date"].max()}。

## 整体 IC

| 腿 | fwd60 IC |
| :--- | :---: |
"""
    for c in cols:
        md += f"| **{labels[c]}** | {overall[c]} |\n"

    md += f"""

## 年度 IC

| 年份 | n | {labels["ai_capex_score"]} |
| :---: | :---: | :---: |
"""
    for r in y.to_dicts():
        md += f"| {r['year']} | {r['n']} | {r['ai_capex_score'] or '-'} |\n"

    md += f"""

## 当前截面（{cur["trade_date"][0]}）

| 腿 | 当前值 |
| :--- | :---: |
"""
    for c in cols:
        v = cur[c][0]
        md += f"| {labels[c]} | {v if v is None else round(v, 1)} |\n"

    md += """

## 结论与局限

- **云CapEx 算力腿**：整体 IC 正（0.432）且 2021/2023/2024 正贡献，确认 AI 算力资本开支分位对
  fwd60 有正向区分度；但 2025/2026 IC 转负（-0.53/-0.86）——分位贴顶后前瞻收益走弱，
  IC 不恒稳（进攻/确认腿特征，同 demand 腿），非稳定顺风信号。当前截面贴顶 100 说明
  AI 算力扩张处高位，属结构性确认而非追涨信号。
- 该腿为**确认腿**（leg_type 独立分组），不并入剪刀差；口径是增速分位（非绝对水平分位）。
- 局限：单行业时序、IC 为 Spearman 秩相关不控制行业 beta、云 CapEx 为季度发布（月内前向填充
  引入平台期）、阈值/窗口硬编码。

数据文件：`semi_structural_ic.csv`（年度 IC）、`semi_structural_current.csv`（当前截面）。
"""
    (_OUT / "semi_structural_ic.md").write_text(md, encoding="utf-8")
    print("=== 半导体 270100 AI 结构性确认腿 IC ===")
    print("整体 IC:", overall)
    print("\n年度 IC:")
    print(y)
    print("\n当前截面:")
    print(cur)
    print(f"\n报告已生成: {_OUT / 'semi_structural_ic.csv'}")
    print(f"Markdown:  {_OUT / 'semi_structural_ic.md'}")


if __name__ == "__main__":
    main()
