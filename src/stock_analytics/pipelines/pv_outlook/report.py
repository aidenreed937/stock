"""光伏景气前瞻仪表盘：Markdown 报告渲染。

报告结构：
1. 核心结论（综合前瞻状态）；2. 价格链与环节毛利空间（周度）；
3. 前瞻读数面板；4. 数据缺口矩阵（明示，可继续补充）；
5. 外部事实核验（强制携带专业信源与发布日期）。
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl

from stock_analytics.pipelines.pv_outlook.config import ExternalFact, PvOutlookConfig

_HEADER = """# 光伏景气前瞻仪表盘（组件 / 辅材 / 硅料）

> **基准日**: {as_of} | **数据底座**: 本地 Curated（InfoLink / 能源局 / 硅业分会 / NBS / 海关派生）
> **用途**: 不等财报（滞后确认），以周度价格链价差与月度供需库存前瞻景气方向。
> **口径声明**: 价差为简化毛利空间（趋势跟踪用，非绝对盈利测算）；本面板为前瞻信号摘要，非已验证因子。
"""


def _render_summary(snapshot: pl.DataFrame) -> str:
    rows = snapshot.filter(pl.col("环节") != "综合")
    positives = rows.filter(pl.col("方向") == "改善").height
    negatives = rows.filter(pl.col("方向") == "走弱").height
    stage_row = snapshot.filter(pl.col("维度") == "前瞻状态").tail(1)
    stage = stage_row["状态"].to_list()[0] if stage_row.height else "NA"
    return (
        "## 一、核心结论\n\n"
        f"- **综合前瞻状态**: {stage}（前瞻读数 {positives} 项改善 / {negatives} 项走弱）\n"
        "- 前瞻读数明细见第三节；数据完整性见第四节缺口矩阵；外部核验见第五节。\n"
    )


def _render_price_chain(price_chain: pl.DataFrame) -> str:
    if price_chain.is_empty():
        return "## 二、价格链与环节毛利空间\n\n- 本地周度价格链缺失（见缺口矩阵）。\n"
    cols = [
        "report_date",
        "polysilicon_price_cny_kg",
        "wafer_price_cny_piece",
        "cell_price_cny_watt",
        "module_price_cny_watt",
        "spread_module_cny_watt",
        "spread_cell_cny_watt",
        "spread_wafer_cny_watt",
        "module_price_yoy",
        "price_cycle_stage",
    ]
    cols = [c for c in cols if c in price_chain.columns]
    recent = price_chain.tail(8)
    lines = [
        "## 二、价格链与环节毛利空间（周度，本地 Curated / InfoLink 口径）\n",
        "| 日期 | 多晶硅(元/kg) | 硅片(元/片) | 电池(元/W) | 组件(元/W) | 组件毛利空间 | 电池毛利空间 | 硅片毛利空间 | 组件同比 | 周期阶段 |",
    ]
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in recent.to_dicts():
        yoy = row.get("module_price_yoy")
        lines.append(
            "| {d} | {p} | {w} | {c} | {m} | {sm:.3f} | {sc:.3f} | {sw:.3f} | {y} | {st} |".format(
                d=row["report_date"],
                p=row.get("polysilicon_price_cny_kg", "NA"),
                w=row.get("wafer_price_cny_piece", "NA"),
                c=row.get("cell_price_cny_watt", "NA"),
                m=row.get("module_price_cny_watt", "NA"),
                sm=row.get("spread_module_cny_watt", float("nan")),
                sc=row.get("spread_cell_cny_watt", float("nan")),
                sw=row.get("spread_wafer_cny_watt", float("nan")),
                y=f"{yoy * 100:+.1f}%"
                if yoy is not None and not (isinstance(yoy, float) and math.isnan(yoy))
                else "NA",
                st=row.get("price_cycle_stage", "NA"),
            )
        )
    lines.append(
        "\n> 简化口径：组件毛利空间=组件价-电池价；电池=电池价-硅片价/6.6W；硅片=硅片价/6.6W-硅料价×2.1g/W。"
    )
    return "\n".join(lines)


def _render_readings(snapshot: pl.DataFrame) -> str:
    lines = ["## 三、前瞻读数面板\n", "| 环节 | 维度 | 读数 | 方向 | 状态 | 说明 |"]
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in snapshot.to_dicts():
        lines.append(
            "| {e} | {d} | {v} | {dir} | {s} | {n} |".format(
                e=row["环节"],
                d=row["维度"],
                v=row["读数"],
                dir=row["方向"],
                s=row["状态"],
                n=row["说明"],
            )
        )
    return "\n".join(lines)


def _render_gaps(gap_matrix: pl.DataFrame) -> str:
    lines = [
        "## 四、数据缺口矩阵（如实明示，可继续补充）\n",
        "| 数据集 | 源端来源 | 节奏 | 最新报告期 | 应有报告期 | 状态 | 说明 |",
    ]
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in gap_matrix.to_dicts():
        status = row["status"]
        badge = {"ok": "正常", "lagging": "滞后", "missing": "缺失"}.get(status, status)
        lines.append(
            "| {ds} | {src} | {cad} | {lp} | {ep} | **{badge}** | {note} |".format(
                ds=row["dataset"],
                src=row["source"],
                cad=row["cadence"],
                lp=row["latest_period"] or "—",
                ep=row["expected_period"],
                badge=badge,
                note=row["note"] or "—",
            )
        )
    missing = gap_matrix.filter(pl.col("status") != "ok").height
    lines.append(
        f"\n> 共 {gap_matrix.height} 个跟踪数据集，{missing} 个存在缺口。缺口项可沿 `stock_data` 采集链补充（NEA/InfoLink/硅业分会/NBS/海关端点）。"
    )
    return "\n".join(lines)


def _render_external(external_facts: tuple[ExternalFact, ...]) -> str:
    lines = [
        "## 五、外部事实核验（专业来源，人工核验输入）\n",
        "> 自动管线不联网；以下事实经外部检索（GrokSearch 等）后人工核验填入配置，强制携带信源与日期。",
        "",
    ]
    if not external_facts:
        lines.append(
            "- 暂无外部核验事实（可在 `config/analytics/pv_outlook.yaml` 的 `external_facts` 补充）。"
        )
        return "\n".join(lines)
    for fact in external_facts:
        url = f" [链接]({fact.url})" if fact.url else ""
        lines.append(f"- {fact.fact}  \n  【专业来源: {fact.source}，{fact.published_date}】{url}")
    return "\n".join(lines)


_FOOTER = """
## 六、口径与限制

1. 本仪表盘为**前瞻信号面板**：价格链为周度实时读数，装机/库存/供需为月度滞后读数（滞后见缺口矩阵）。
2. 财报（业绩预告/三季报）属滞后确认层，不在本面板内；Q3 预告窗口（10 月上旬）可另行验证。
3. 外部事实仅作背景核验，不替代本地 Curated 读数；信源与日期强制标注。
4. 所有读数均来自本地 Curated 黄金表，本地缺失如实标记，未补造任何数值。
"""


def render_pv_outlook_markdown(
    config: PvOutlookConfig,
    as_of: date,
    snapshot: pl.DataFrame,
    price_chain: pl.DataFrame,
    gap_matrix: pl.DataFrame,
) -> str:
    """渲染完整 Markdown 报告。"""
    sections = [
        _HEADER.format(as_of=as_of),
        _render_summary(snapshot),
        _render_price_chain(price_chain),
        _render_readings(snapshot),
        _render_gaps(gap_matrix),
        _render_external(config.external_facts),
        _FOOTER,
    ]
    return "\n".join(sections)
