"""量化体检报告纯视图渲染器 (Presentation Layer)。

设计原则:
    1. 纯无状态渲染器: 零业务决策分支逻辑，仅负责将 DailyMarketScanSummary 渲染为 Markdown 或卡片；
    2. 类型安全: 直接消费强类型领域聚合根 DailyMarketScanSummary (兼容字典输入自动解析)；
    3. 支持普通投资者版、专业量化版与终端控制台 ASCII 卡片三种展示形式。
"""

from __future__ import annotations

from typing import Any

from stock.analytics.models import DailyMarketScanSummary


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

    # 1. 行业怎么选
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

    signal_rows = []
    for s in summary.signals:
        val_str = s.value_str
        if "股债" in s.name and eyby_dt < dt_str:
            val_str += f" ({eyby_dt[5:]}前值)"
        elif "全 A" in s.name and allm_dt < dt_str:
            val_str += f" ({allm_dt[5:]}前值)"
        signal_rows.append(
            f"| {s.category} | {s.name} | {val_str} | {s.percentile_str} | "
            f"{s.status} {s.description} |"
        )

    # 3. 微观健康度
    mh = summary.micro_health
    margin_tag = f" ({m_dt[5:]}前值)" if m_dt < dt_str else ""

    # 4. 数据时效审计清单
    stale_items = []
    if eyby_dt < dt_str:
        stale_items.append(f"- ⚠️ 股债收益比 (000300)：实际截止 **{eyby_dt}** (滞后沿用)")
    if allm_dt < dt_str:
        stale_items.append(f"- ⚠️ 全 A 资产水位 (000985)：实际截止 **{allm_dt}** (滞后沿用)")
    if m_dt < dt_str:
        stale_items.append(f"- ℹ️ 融资融券数据：实际截止 **{m_dt}** (交易所官方 T+1 次日发布)")

    if stale_items:
        timing_section = ["## 数据时效说明", *stale_items, ""]
    else:
        timing_section = [
            "## 数据时效说明",
            f"- 🟢 全部宏观估值、行业中观与微观情绪数据均已对齐至当日最新 ({dt_str})。",
            "",
        ]

    lines = [
        f"# 📈 A 股每日体检 · {dt_str}",
        "",
        "## 一句话结论",
        summary.one_sentence_summary,
        "",
        "## 四个关键信号",
        "| 类型 | 信号 | 关键数字 | 10年分位 | 说明 / 定性 |",
        "|---|---|---|---|---|",
        *signal_rows,
        "",
        "## 行业怎么选",
        f"- 🟢 低估洼地：**{uv_str}**（质优价廉）",
        crowd_line,
        "",
        "## 微观健康度",
        f"- 两融杠杆：**{mh.margin_ratio:.2f}%**{margin_tag}（{mh.margin_status}）",
        f"- 破净比例：**{mh.pb_break_ratio:.2f}%**（{mh.pb_break_status}）",
        f"- 市场换手：**{mh.turnover_ratio:.2f}%**（{mh.turnover_status}）",
        f"- 中期趋势：**{mh.above_ma60_ratio:.1f}%** 站上 60 日线（{mh.ma60_status}）",
        "",
        *timing_section,
        "## 操作备忘",
        *summary.action_items,
        "",
    ]
    return "\n".join(lines)


def _render_pro_macro_section(summary: DailyMarketScanSummary, dt_str: str) -> list[str]:
    """生成专业版宏观节内容。"""
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
        f"PE: {all_m.pe_ttm_ew:.2f} (Pctl: {all_m.pe_percentile_10y:.1f}%)"
        if all_m
        else "N/A"
    )
    buf_s = (
        f"{buffett.securitization_ratio:.1f}%{buf_tag} (MV: {buffett.total_market_cap_yi:.0f}亿, "
        f"Pctl: {buffett.percentile_10y:.1f}%)"
        if buffett
        else "N/A"
    )

    reg_val = macro.regime.value if macro else "NORMAL_ROTATION"
    reg_desc = macro.regime_desc if macro else ""
    exp_val = (macro.suggested_equity_exposure * 100) if macro else 70.0
    macro_dt = macro.trade_date.strftime("%Y-%m-%d") if macro else dt_str
    macro_stale_warn = " ⚠️ 滞后沿用" if macro_dt < dt_str else ""

    lines = [
        f"## 1. 宏观周期与大类资产定价 (Macro Regime, As-Of: {macro_dt}{macro_stale_warn})",
        f"- **Regime**: `{reg_val}` ({reg_desc})",
        f"- **Exposure Limit**: `{exp_val:.1f}%`",
        f"- **EY/BY Ratio (000300)**: `{eyby_s}`",
        f"- **All-Market PB (000985)**: `{all_m_s}`",
        f"- **Buffett Ratio (MV/GDP)**: `{buf_s}`",
        "- **Key Drivers**:",
    ]
    if macro:
        for d in macro.key_drivers:
            lines.append(f"  - {d}")
    return lines


def _render_pro_industry_section(summary: DailyMarketScanSummary, dt_str: str) -> list[str]:
    """生成专业版中观行业节内容。"""
    tcr = summary.tcr
    pbroe = summary.pbroe
    momentum = summary.momentum

    t1_n = summary.top1_industry
    t1_p = summary.top1_tcr
    t_amt = tcr.total_amount_yi if tcr else 0.0
    tcr_dt = tcr.trade_date.strftime("%Y-%m-%d") if tcr else dt_str
    pbroe_dt = pbroe.trade_date.strftime("%Y-%m-%d") if pbroe else dt_str

    tcr_warn = " ⚠️ 滞后" if tcr_dt < dt_str else ""
    pbroe_warn = " ⚠️ 滞后" if pbroe_dt < dt_str else ""

    p_alpha = pbroe.regression_alpha if pbroe else 0.0
    p_beta = pbroe.regression_beta if pbroe else 0.0
    p_r2 = pbroe.r_squared if pbroe else 0.0
    mom_spread = momentum.spread if momentum else 0.0

    header = (
        f"## 2. 中观行业轮动与风控 (TCR As-Of: {tcr_dt}{tcr_warn}, "
        f"PB-ROE As-Of: {pbroe_dt}{pbroe_warn})"
    )

    return [
        header,
        f"- **Total Amount**: `{t_amt:.1f} 亿元`",
        f"- **Top 1 Industry**: `{t1_n}` ({t1_p:.1f}%)",
        f"- **Crowded Industries**: `{summary.crowded_industries}`",
        f"- **PB-ROE Fit**: `R²={p_r2:.3f} (α: {p_alpha:.3f}, β: {p_beta:.4f})`",
        f"- **Undervalued Industries**: `{summary.undervalued_industries}`",
        f"- **Momentum Spread**: `{mom_spread:.1f}%`",
    ]


def _render_pro_micro_section(summary: DailyMarketScanSummary, dt_str: str) -> list[str]:
    """生成专业版微观博弈节内容。"""
    margin = summary.margin
    breadth = summary.breadth
    sentiment = summary.sentiment

    m_bal = margin.margin_balance_yi if margin else 0.0
    m_ratio = margin.margin_penetration if margin else 0.0
    m_dt = margin.trade_date.strftime("%Y-%m-%d") if margin else dt_str
    m_tag = f" [{m_dt[5:]}前值]" if m_dt < dt_str else ""

    b20 = breadth.above_ma20_ratio if breadth else 0.0
    b60 = breadth.above_ma60_ratio if breadth else 0.0
    b120 = breadth.above_ma120_ratio if breadth else 0.0
    pbb = sentiment.pb_break_ratio if sentiment else 0.0
    to = sentiment.turnover_ratio if sentiment else 0.0

    return [
        f"## 3. 微观博弈与流动性情绪 (Margin As-Of: {m_dt}{m_tag})",
        f"- **Margin Penetration**: `{m_ratio:.2f}%` (Balance: {m_bal:.1f} 亿)",
        f"- **Breadth**: MA20 `{b20:.1f}%` | MA60 `{b60:.1f}%` | MA120 `{b120:.1f}%`",
        f"- **Sentiment**: PB Break `{pbb:.2f}%` | Turnover `{to:.2f}%`",
    ]


def format_pro_report(data_or_summary: DailyMarketScanSummary | dict[str, Any]) -> str:
    """生成面向专业量化与大模型对账审查的专业结构化 Markdown 报告。"""
    summary = _ensure_summary(data_or_summary)
    dt_str = summary.trade_date.strftime("%Y-%m-%d")

    lines = [
        f"# 📊 A 股量化全景体检专业报告 (基准日: {dt_str})",
        "",
        "---",
        "",
    ]
    lines.extend(_render_pro_macro_section(summary, dt_str))
    lines.append("")
    lines.extend(_render_pro_industry_section(summary, dt_str))
    lines.append("")
    lines.extend(_render_pro_micro_section(summary, dt_str))
    lines.append("")
    return "\n".join(lines)


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
