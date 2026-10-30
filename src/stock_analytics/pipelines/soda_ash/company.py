"""纯碱上市公司盈利与估值反向时钟对账面板渲染（数据驱动）。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.soda_ash.formatting import (
    _fmt_amt,
    _fmt_imp,
    _fmt_pct,
    _fmt_share,
    _fmt_val,
    _process_cn,
)


def _render_company_section(company_panel: pl.DataFrame | None) -> str:
    if company_panel is None or company_panel.is_empty():
        return "\n---\n\n## 五、 纯碱上市公司盈利与估值反向时钟对账面板\n\n（公司面板无数据）"

    latest_companies = (
        company_panel.sort("trade_date").group_by("symbol").last().sort(["process_type", "symbol"])
    )
    latest_trade_date = str(company_panel["trade_date"].max())

    fin_rows = _company_fin_rows(latest_companies)
    val_rows = _company_val_rows(latest_companies)
    metrics = _collect_company_metrics(latest_companies)

    table_1 = "\n".join(
        [
            "| 标的代码 | 公司名称 | 工艺路线 | 财报期 | 营业总收入 (亿元) | 归母净利润 (亿元) | 资产减值损失 (万元) | 存货余额 (亿元) | 纯碱营收暴露 |",
            "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
            *fin_rows,
        ]
    )
    table_2 = "\n".join(
        [
            f"### 2. 估值反向时钟与市场定价诊断 (最新交易日: `{latest_trade_date}`)",
            "",
            "| 标的代码 | 公司名称 | 工艺路线 | 收盘价 (元) | 总市值 (亿元) | PB (市净率) | PB 10Y 分位 | PE-TTM | 反向时钟状态 |",
            "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
            *val_rows,
        ]
    )
    narrative = _render_company_narrative(metrics)

    return "\n".join(
        [
            "---",
            "",
            "## 五、 纯碱上市公司盈利与估值反向时钟对账面板",
            "",
            "### 1. 核心上市公司最新季报财务与减值对账表",
            table_1,
            "",
            table_2,
            "",
            "### 3. 周期反向时钟量化实证与配置启示（数据驱动）",
            narrative,
        ]
    )


def _company_fin_rows(latest: pl.DataFrame) -> list[str]:
    rows: list[str] = []
    for r in latest.iter_rows(named=True):
        imp = f"{r['assets_impair_loss'] / 1e4:+.0f}" if r["assets_impair_loss"] else "--"
        soda_share = (
            r.get("soda_revenue_share")
            if r.get("soda_revenue_share") is not None
            else r.get("soda_revenue_share_approx")
        )
        rows.append(
            f"| `{r['symbol']}` | **{r['company_name']}** | `{_process_cn(r['process_type'])}` | "
            f"`{r['fin_report_date'] or '--'}` | {_fmt_amt(r.get('total_revenue'))} | "
            f"{_fmt_amt(r.get('net_profit_attr_p'), signed=True)} | {imp} | "
            f"{_fmt_amt(r.get('inventories'))} | {_fmt_share(soda_share)} |"
        )
    return rows


def _company_val_rows(latest: pl.DataFrame) -> list[str]:
    rows: list[str] = []
    for r in latest.iter_rows(named=True):
        close = f"{r['close']:.2f}" if r["close"] else "--"
        mv = f"{r['total_mv'] / 1e8:.1f}" if r["total_mv"] else "--"
        pb = f"{r['pb']:.2f}" if r["pb"] else "--"
        pb10y = f"{r['pb_percentile_10y']:.1f}%" if r["pb_percentile_10y"] is not None else "--"
        pe = f"{r['pe_ttm']:.1f}" if r["pe_ttm"] else "--"
        regime = r["valuation_regime"] or "neutral"
        rows.append(
            f"| `{r['symbol']}` | **{r['company_name']}** | `{_process_cn(r['process_type'])}` | "
            f"{close} | {mv} | {pb} | **{pb10y}** | {pe} | `{regime}` |"
        )
    return rows


def _collect_company_metrics(latest: pl.DataFrame) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "total": len(latest),
        "loss_rows": [],
        "deep_value_rows": [],
        "fair_expansion_rows": [],
        "loss_count": 0,
        "impairment_total": 0.0,
    }
    for r in latest.iter_rows(named=True):
        np_val = r.get("net_profit_attr_p")
        if np_val is not None and float(np_val) < 0:
            metrics["loss_count"] += 1
            metrics["loss_rows"].append(
                f"- {r['company_name']}（{_process_cn(r['process_type'])}）"
                f"`{r['fin_report_date'] or '--'}` 归母净利润 {_fmt_amt(np_val, signed=True)} 亿元，"
                f"资产减值损失 {_fmt_imp(r.get('assets_impair_loss'))} 万元"
            )
        imp_val = r.get("assets_impair_loss")
        if imp_val is not None:
            metrics["impairment_total"] += float(imp_val)

        regime = r.get("valuation_regime")
        if regime == "deep_value_trough":
            metrics["deep_value_rows"].append(
                f"- {r['company_name']}（{_process_cn(r['process_type'])}）PB `{_fmt_val(r.get('pb'), 2)}`，"
                f"PB 10Y 分位 `{_fmt_pct(r.get('pb_percentile_10y'))}` 触发 `deep_value_trough`"
            )
        elif regime == "fair_expansion":
            metrics["fair_expansion_rows"].append(
                f"- {r['company_name']}（{_process_cn(r['process_type'])}）PB 10Y 分位 "
                f"`{_fmt_pct(r.get('pb_percentile_10y'))}`，处于 `fair_expansion` 状态"
            )
    return metrics


def _render_company_narrative(metrics: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.append("1. **边际出清传导实证**（数据实证）:")
    if metrics["loss_rows"]:
        parts.extend(metrics["loss_rows"])
        parts.append(
            f"   - 最新季报窗口共 {metrics['loss_count']} 家出现归母净利润为负，"
            f"资产减值损失合计 `{metrics['impairment_total'] / 1e4:,.0f}` 万元，"
            "印证现货价格/价差跌穿边际现金保本线后将在报表端引发非线性利润坍塌（机制推断）。"
        )
    else:
        parts.append("   - 最新季报窗口样本公司均维持正利润，暂无报表端亏损出清信号。")

    parts.append("2. **估值反向时钟规律**（数据实证）:")
    if metrics["deep_value_rows"]:
        parts.extend(metrics["deep_value_rows"])
        parts.append(
            "   - 极低 PB 分位往往对应周期左侧深价值高赔率区间；"
            "此时 PE 可能因亏损转负，需以 PB/现金流视角评估（机制推断）。"
        )
    else:
        parts.append("   - 当前样本暂无公司处于 `deep_value_trough` 状态。")

    parts.append("3. **低成本龙头抗亏阿尔法**（数据实证）:")
    if metrics["fair_expansion_rows"]:
        parts.extend(metrics["fair_expansion_rows"])
    else:
        parts.append("   - 当前样本暂无公司处于 `fair_expansion` 状态。")

    deep_count = len(metrics["deep_value_rows"])
    if metrics["loss_count"] >= 2 and deep_count >= 2:
        parts.append(
            "4. **配置含义（机制推断，非投资建议）**: 高成本工艺亏损出清 + 深度价值分位共振，"
            "周期左侧结构性配置性价比窗口特征明显，需等待价格/利润拐点确认。"
        )
    elif metrics["loss_count"] == 0 and deep_count == 0:
        parts.append(
            "4. **配置含义（机制推断，非投资建议）**: 行业利润与估值均未到极端状态，"
            "维持基本面跟踪、等右侧确认。"
        )
    else:
        parts.append(
            "4. **配置含义（机制推断，非投资建议）**: 分化格局，优先跟踪低成本头寸的盈利韧性"
            "与高成本装置的边际出清节奏。"
        )
    return "\n".join(parts)


__all__ = ["_render_company_section"]
