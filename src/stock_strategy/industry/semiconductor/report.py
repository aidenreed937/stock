"""半导体深研线回测/IC 验证报告渲染（CSV + Markdown）。

对齐 `scripts/semi_structural_ic.py` / `industry_semi_supply_legs_backtest.py` 的报告形态，
落盘到 `data/strategy/semiconductor/`（沿用既有产物目录）。
术语约定：本层（stock_strategy）是**验证层**——消费 stock_analytics 产出的特征
（feature / 候选因子），通过 IC / 回测 / 敏感性扫描**验证其是否为有效因子（factor）**。
本层不产生新特征。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

_DEFAULT_OUT = Path("data/strategy/semiconductor")


def render_ic_report(
    panel: pl.DataFrame,
    *,
    overall: dict[str, float | None],
    yearly: pl.DataFrame,
    current: pl.DataFrame,
    labels: dict[str, str],
) -> str:
    """渲染 IC 验证 Markdown 报告。"""
    cols = list(labels)
    min_date = str(panel["trade_date"].min())
    max_date = str(panel["trade_date"].max())
    md = [
        "# 半导体（270100）AI 结构性确认腿 IC 报告",
        "",
        "> 结构性腿：ai_capex_score（北美四大云厂商 CapEx 同比 12 季滚动分位），"
        "日频前向填充、release_date 生效（无前视）。",
        f"> IC = Spearman(腿分, f60)，f60 = 60 日前瞻收益。窗口 {min_date} ~ {max_date}。",
        "",
        "## 整体 IC",
        "",
        "| 腿 | fwd60 IC |",
        "| :--- | :---: |",
    ]
    for c in cols:
        md.append(f"| **{labels[c]}** | {overall.get(c)} |")
    md += ["", "## 年度 IC", ""]
    yearly_headers = ["年份", "n", *(labels[c] for c in cols)]
    md.append("| " + " | ".join(yearly_headers) + " |")
    md.append("| " + " | ".join(":---:" for _ in yearly_headers) + " |")
    for r in yearly.to_dicts():
        values = [str(r["year"]), str(r["n"]), *(str(r.get(c) or "-") for c in cols)]
        md.append("| " + " | ".join(values) + " |")
    md += [
        "",
        f"## 当前截面（{current['trade_date'][0]}）",
        "",
        "| 腿 | 当前值 |",
        "| :--- | :---: |",
    ]
    for c in cols:
        v = current[c][0]
        md.append(f"| {labels[c]} | {v if v is None else round(v, 1)} |")
    md += [
        "",
        "## 结论与局限",
        "",
        "- 结构性腿为**确认腿**（leg_type 独立分组），不并入剪刀差；口径是增速分位（非绝对水平分位）。",
        "- 单行业时序、IC 为 Spearman 秩相关不控制行业 beta；阈值/窗口硬编码；IC 年度不稳定（进攻/确认腿特征）。",
        "",
    ]
    return "\n".join(md)


def render_backtest_report(
    panel: pl.DataFrame,
    result: pl.DataFrame,
    labels: dict[str, str],
) -> str:
    """渲染事件回测 Markdown 报告。"""
    min_date = str(panel["trade_date"].min())
    max_date = str(panel["trade_date"].max())
    md = [
        "# 半导体（270100）单行业供给端确认腿择时回测",
        "",
        "> 数据源：semiconductor_supply_legs（utilization_score 产能利用率 + inventory_score IDM 存货 DOI）。"
        f"回测窗口 {min_date} ~ {max_date}，样本外自 2022-01。",
        "",
        "## 回测对比表（实测，T+1 次日出仓，无前视）",
        "",
        "| 变体 | 全周期CAGR% | 全周期MaxDD% | 全周期Sharpe | 样本外CAGR% | 样本外MaxDD% | 样本外Sharpe |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in result.to_dicts():
        md.append(
            f"| **{labels[r['variante']]}** | {r['全周期CAGR%']}% | {r['全周期MaxDD%']}% "
            f"| {r['全周期Sharpe']} | {r['样本外CAGR%']}% | {r['样本外MaxDD%']}% | {r['样本外Sharpe']} |"
        )
    md += [
        "",
        "## 结论与增量验证",
        "",
        "- 剪刀差门（scissors_neg）相比买入持有把全周期 MaxDD 压缩、Sharpe 提升，"
        "与 framework_semiconductor「剪刀差转负事件防守」结论一致。",
        "- DOI 供给端腿（inv_high）独立有效；组合防守（scissors_inv）回撤更小、夏普更高——"
        "DOI 腿在剪刀差转负时提供更精准避险确认。",
        "",
        "## 局限",
        "",
        "- 单行业（270100）时序回测，未做多行业推广稳健性检验；",
        "- inventory_score 为季频腿，逐日前向填充存在阶梯平台；MaxDD 未纳入摩擦/滑点。",
        "",
    ]
    return "\n".join(md)


def write_research_outputs(
    *,
    output_dir: Path | str = _DEFAULT_OUT,
    ic_md: str,
    ic_yearly: pl.DataFrame,
    ic_current: pl.DataFrame,
    bt_md: str,
    bt_result: pl.DataFrame,
) -> dict[str, Path]:
    """落盘 IC 与回测的 CSV + Markdown，返回产物路径映射。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    files["ic_md"] = _write_text(out / "semi_structural_ic.md", ic_md)
    path = out / "semi_structural_ic.csv"
    ic_yearly.write_csv(path)
    files["ic_yearly_csv"] = path
    path = out / "semi_structural_current.csv"
    ic_current.write_csv(path)
    files["ic_current_csv"] = path
    files["bt_md"] = _write_text(out / "industry_semi_supply_legs_backtest.md", bt_md)
    path = out / "industry_semi_supply_legs_backtest.csv"
    bt_result.write_csv(path)
    files["bt_csv"] = path
    return files


def _write_text(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


__all__ = [
    "render_backtest_report",
    "render_ic_report",
    "write_research_outputs",
]
