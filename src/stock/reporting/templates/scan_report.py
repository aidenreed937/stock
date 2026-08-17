"""量化体检报告纯视图渲染器 (Presentation Layer)。

设计原则:
    1. 纯无状态渲染器: 零业务决策分支逻辑，仅负责将 DailyMarketScanSummary 渲染为 Markdown 或卡片；
    2. 类型安全: 直接消费强类型领域聚合根 DailyMarketScanSummary (兼容字典输入自动解析)；
    3. 基于 Jinja2 模板驱动: 视图排版由 .md.j2 模板声明式管理，代码仅负责组装渲染上下文；
    4. 支持普通投资者版、专业量化版与终端控制台 ASCII 卡片三种展示形式。
"""

from __future__ import annotations

from typing import Any

from stock.analytics.models import DailyMarketScanSummary
from stock.reporting.engine.renderer import ReportRenderer


def _ensure_summary(
    data_or_summary: DailyMarketScanSummary | dict[str, Any],
) -> DailyMarketScanSummary:
    """确保输入为强类型的 DailyMarketScanSummary 对象。"""
    if isinstance(data_or_summary, DailyMarketScanSummary):
        return data_or_summary
    return DailyMarketScanSummary.model_validate(data_or_summary)


def format_investor_report(data_or_summary: DailyMarketScanSummary | dict[str, Any]) -> str:
    """生成面向普通投资者的清晰干练、一屏结论导向的每日体检 Markdown 报告。"""
    summary = _ensure_summary(data_or_summary)
    dt_str = summary.trade_date.strftime("%Y-%m-%d")

    # 1. 行业拥挤度文案
    uv_str = "、".join(summary.undervalued_industries[:4]) or "暂无显著偏离板块"
    if summary.crowded_industries:
        crowd_line = (
            f"- 🔴 拥挤警戒：**{summary.top1_industry}** "
            f"成交占 {summary.top1_tcr:.1f}%（>20% 警戒线）"
        )
    else:
        crowd_line = (
            f"- 🟢 拥挤警戒：全市场行业成交分布均衡"
            f"（最高 {summary.top1_industry} 占 {summary.top1_tcr:.1f}%）"
        )

    # 2. 信号表格 (带滞后时效显式标注)
    macro = summary.macro
    margin = summary.margin
    m_dt = margin.trade_date.strftime("%Y-%m-%d") if margin else dt_str
    eyby_dt = macro.ey_by.trade_date.strftime("%Y-%m-%d") if (macro and macro.ey_by) else dt_str
    allm_dt = (
        macro.all_market.trade_date.strftime("%Y-%m-%d") if (macro and macro.all_market) else dt_str
    )

    signals_payload = []
    for s in summary.signals:
        val_str = s.value_str
        if "股债" in s.name and eyby_dt < dt_str:
            val_str += f" ({eyby_dt[5:]}前值)"
        elif "全 A" in s.name and allm_dt < dt_str:
            val_str += f" ({allm_dt[5:]}前值)"
        signals_payload.append(
            {
                "category": s.category,
                "name": s.name,
                "value_display": val_str,
                "percentile_str": s.percentile_str,
                "status": s.status,
                "description": s.description,
            }
        )

    # 3. 微观健康度标签
    margin_tag = f" ({m_dt[5:]}前值)" if m_dt < dt_str else ""

    # 4. 数据时效审计清单
    stale_items = []
    if eyby_dt < dt_str:
        stale_items.append(f"⚠️ 股债收益比 (000300)：实际截止 **{eyby_dt}** (滞后沿用)")
    if allm_dt < dt_str:
        stale_items.append(f"⚠️ 全 A 资产水位 (000985)：实际截止 **{allm_dt}** (滞后沿用)")
    if m_dt < dt_str:
        stale_items.append(f"ℹ️ 融资融券数据：实际截止 **{m_dt}** (交易所官方 T+1 次日发布)")

    context = {
        "trade_date": dt_str,
        "summary": summary,
        "signals": signals_payload,
        "undervalued_str": uv_str,
        "crowd_line": crowd_line,
        "margin_tag": margin_tag,
        "stale_items": stale_items,
    }

    return ReportRenderer.get_instance().render("scan/investor.md.j2", context)


def format_pro_report(data_or_summary: DailyMarketScanSummary | dict[str, Any]) -> str:
    """生成面向专业量化与大模型对账审查的专业结构化 Markdown 报告。"""
    summary = _ensure_summary(data_or_summary)
    dt_str = summary.trade_date.strftime("%Y-%m-%d")

    macro = summary.macro
    eyby = macro.ey_by if macro else None
    all_m = macro.all_market if macro else None
    buffett = macro.buffett if macro else None

    eyby_dt = eyby.trade_date.strftime("%Y-%m-%d") if eyby else dt_str
    allm_dt = all_m.trade_date.strftime("%Y-%m-%d") if all_m else dt_str
    buf_dt = buffett.trade_date.strftime("%Y-%m-%d") if buffett else dt_str

    eyby_tag = f" [⚠️ {eyby_dt[5:]}前值]" if eyby_dt < dt_str else ""
    allm_tag = f" [⚠️ {allm_dt[5:]}前值]" if allm_dt < dt_str else ""
    buf_tag = f" [⚠️ {buf_dt[5:]}前值]" if buf_dt < dt_str else ""

    eyby_s = (
        f"{eyby.ey_by_ratio:.2f}x{eyby_tag} (PE: {eyby.pe_ttm:.2f}, "
        f"10Y: {eyby.bond_yield_10y:.3f}%, Pctl: {eyby.percentile_10y:.1f}%)"
        if eyby
        else "N/A"
    )
    all_m_s = (
        f"PB: {all_m.pb_ew:.3f}{allm_tag} (Pctl: {all_m.pb_percentile_10y:.1f}%), "
        f"PE: {all_m.pe_ttm_ew:.2f} (Pctl: {all_m.pe_percentile_10y:.1f}% "
        f"[⚠️ 等权PE受微利股拉升，以PB为主基准])"
        if all_m
        else "N/A"
    )
    buf_s = (
        f"{buffett.securitization_ratio:.1f}%{buf_tag} (MV: {buffett.total_market_cap_yi:.0f}亿, "
        f"Pctl: {buffett.percentile_10y:.1f}%)"
        if buffett
        else "N/A"
    )

    tcr = summary.tcr
    pbroe = summary.pbroe
    momentum = summary.momentum
    tcr_dt = tcr.trade_date.strftime("%Y-%m-%d") if tcr else dt_str
    pbroe_dt = pbroe.trade_date.strftime("%Y-%m-%d") if pbroe else dt_str

    margin = summary.margin
    breadth = summary.breadth
    sentiment = summary.sentiment
    m_dt = margin.trade_date.strftime("%Y-%m-%d") if margin else dt_str

    context = {
        "trade_date": dt_str,
        "macro_dt": macro.trade_date.strftime("%Y-%m-%d") if macro else dt_str,
        "macro_stale_warn": (
            " ⚠️ 滞后沿用" if (macro and macro.trade_date.strftime("%Y-%m-%d") < dt_str) else ""
        ),
        "macro_regime": macro.regime.value if macro else "NORMAL_ROTATION",
        "macro_regime_desc": macro.regime_desc if macro else "",
        "macro_exposure": (macro.suggested_equity_exposure * 100) if macro else 70.0,
        "eyby_s": eyby_s,
        "all_m_s": all_m_s,
        "buf_s": buf_s,
        "macro_key_drivers": macro.key_drivers if macro else [],
        "tcr_dt": tcr_dt,
        "tcr_warn": " ⚠️ 滞后" if tcr_dt < dt_str else "",
        "pbroe_dt": pbroe_dt,
        "pbroe_warn": " ⚠️ 滞后" if pbroe_dt < dt_str else "",
        "total_amount": tcr.total_amount_yi if tcr else 0.0,
        "top1_industry": summary.top1_industry,
        "top1_tcr": summary.top1_tcr,
        "crowded_industries": summary.crowded_industries,
        "pbroe_r2": pbroe.r_squared if pbroe else 0.0,
        "pbroe_alpha": pbroe.regression_alpha if pbroe else 0.0,
        "pbroe_beta": pbroe.regression_beta if pbroe else 0.0,
        "undervalued_industries": summary.undervalued_industries,
        "momentum_spread": momentum.spread if momentum else 0.0,
        "margin_dt": m_dt,
        "margin_tag": f" [{m_dt[5:]}前值]" if m_dt < dt_str else "",
        "margin_penetration": margin.margin_penetration if margin else 0.0,
        "margin_balance": margin.margin_balance_yi if margin else 0.0,
        "breadth_ma20": breadth.above_ma20_ratio if breadth else 0.0,
        "breadth_ma60": breadth.above_ma60_ratio if breadth else 0.0,
        "breadth_ma120": breadth.above_ma120_ratio if breadth else 0.0,
        "pb_break": sentiment.pb_break_ratio if sentiment else 0.0,
        "turnover": sentiment.turnover_ratio if sentiment else 0.0,
    }

    return ReportRenderer.get_instance().render("scan/pro.md.j2", context)


def format_card_summary(data_or_summary: DailyMarketScanSummary | dict[str, Any]) -> str:
    """生成终端控制台紧凑 ASCII 卡片输出。"""
    summary = _ensure_summary(data_or_summary)
    dt = summary.trade_date.strftime("%Y-%m-%d")
    macro = summary.macro
    reg_desc = macro.regime_desc if macro else "常态合理轮动"
    exp = (macro.suggested_equity_exposure * 100) if macro else 70.0

    top1 = summary.top1_industry
    tcr_p = summary.top1_tcr
    m_pen = summary.micro_health.margin_ratio
    pb_b = summary.micro_health.pb_break_ratio

    lines = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        f"║  A 股量化体检全景摘要 ({dt})                                    ║",
        "╠══════════════════════════════════════════════════════════════════════╣",
        f"║  宏观状态: {reg_desc[:36]:<36} ║",
        f"║  建议仓位: {exp:>5.1f}%  |  行业焦点: {top1} (占比 {tcr_p:.1f}%)        ║",
        f"║  微观特征: 两融 {m_pen:.2f}% | 破净率 {pb_b:.2f}%                           ║",
        "╚══════════════════════════════════════════════════════════════════════╝",
    ]
    return "\n".join(lines)


# 控制台报告格式化别名
format_console_report = format_card_summary
