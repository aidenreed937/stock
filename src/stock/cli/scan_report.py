"""量化体检报告格式化器 (支持普通投资者通俗版、专业量化版与终端控制台卡片)。"""

from __future__ import annotations

from typing import Any, Final

from stock.analytics.industry.classifier import IndustryClassifier

REGIME_CN_NAMES: Final[dict[str, str]] = {
    "OPPORTUNITY_ZONE": "🟢 战略黄金建仓期 (大级别大底)",
    "BUBBLE_RISK": "🔴 周期大顶泡沫区 (极度过热风险)",
    "DEFENSIVE": "🟡 中性防守观察期 (控制风险)",
    "NORMAL_ROTATION": "⚪ 常态结构轮动期 (适度均衡)",
}

_CLASSIFIER = IndustryClassifier()


def _resolve_industry_name(code_or_name: str) -> str:
    """将代码转换为标准行业中文名称。"""
    return _CLASSIFIER.resolve_name(code_or_name)


def _get_regime_advice(regime: str) -> tuple[str, str, str]:
    """获取宏观周期的评级标签、纯中文名称与白话指引。"""
    cn_name = REGIME_CN_NAMES.get(regime, "⚪ 常态结构轮动期 (适度均衡)")
    if regime == "OPPORTUNITY_ZONE":
        badge = "⭐⭐⭐⭐⭐ 战略级黄金机会区 (高胜率高赔率)"
        advice = "市场处于历史极低估值大底，战略胜率与赔率极高，建议保持重仓并坚定持有。"
    elif regime == "BUBBLE_RISK":
        badge = "⚠️ 周期大顶泡沫警戒区 (极高风险)"
        advice = "市场估值严重过热与收益率倒挂，建议强制压降仓位至防守底线，坚决避险。"
    elif regime == "DEFENSIVE":
        badge = "🛡️ 中性防御区 (适度控制风险)"
        advice = "估值或杠杆有所积聚，建议控制在半仓以下，聚焦防御底仓或低估值品种。"
    else:
        badge = "🔄 常态合理轮动区 (结构性阿尔法)"
        advice = "宏观估值适中，无系统性风险，建议标准仓位配置，主打行业轮动与选股。"
    return badge, cn_name, advice


def _build_one_sentence_summary(data: dict[str, Any]) -> str:
    """构建一句话结论：裁决核心矛盾，给出仓位与行业配置方向。"""
    macro = data.get("macro") or {}
    eyby = macro.get("ey_by") or {}
    all_m = macro.get("all_market") or {}
    buffett = macro.get("buffett") or {}
    pbroe = data.get("pbroe") or {}
    tcr = data.get("tcr") or {}

    eyby_val = eyby.get("ey_by_ratio", 0.0)
    eyby_pctl = eyby.get("percentile_10y", 0.0)
    pb_pctl = all_m.get("pb_percentile_10y", 50.0)
    buf_pctl = buffett.get("percentile_10y", 0.0)
    exp_pct = macro.get("suggested_equity_exposure", 0.7) * 100

    undervalued_raw = pbroe.get("undervalued_industries", [])
    uv_names = [_resolve_industry_name(c) for c in undervalued_raw[:3]]
    uv_str = "/".join(uv_names) if uv_names else "低估高股息"

    crowded = [_resolve_industry_name(c) for c in tcr.get("crowded_industries", [])]
    crowd_str = "/".join(crowded) if crowded else "高位题材"

    if eyby_pctl >= 70.0 and (buf_pctl >= 80.0 or pb_pctl > 60.0):
        return (
            f"股票性价比处于历史高位（沪深300 股债比 {eyby_val:.2f}x，"
            f"10 年 {eyby_pctl:.0f}% 分位），"
            f"但全 A 水位处于 {pb_pctl:.0f}% 中枢偏上，证券化率达 {buf_pctl:.0f}% 高分位——"
            f"便宜主要靠超低国债利率与大盘蓝筹，全 A 并非全面低估。"
            f"**保持 {exp_pct:.0f}% 仓位，只买便宜好货（{uv_str}），回避过热板块（{crowd_str}）。**"
        )
    if eyby_pctl >= 70.0:
        return (
            f"股票资产处于高性价比战略建仓期（股债比 {eyby_val:.2f}x，"
            f"10 年 {eyby_pctl:.0f}% 分位）。"
            f"**保持 {exp_pct:.0f}% 积极仓位，重点配置质优价廉资产（{uv_str}）。**"
        )
    if eyby_pctl < 30.0 or buf_pctl >= 90.0:
        return (
            f"市场估值与杠杆处于偏热风险区。"
            f"**建议将仓位严格控制在 {exp_pct:.0f}% 防御水平，坚决避险。**"
        )
    return (
        f"宏观估值处于常态中枢区间，无系统性风险。"
        f"**建议维持 {exp_pct:.0f}% 标准配置，优选 {uv_str}。**"
    )


def _render_eyby_row(eyby: dict[str, Any]) -> str:
    val = eyby.get("ey_by_ratio", 0.0)
    pctl = eyby.get("percentile_10y", 0.0)
    if pctl >= 70.0:
        st, desc = "🟢 高", f"历史性机会，仅 {100 - pctl:.0f}% 时间更便宜"
    elif pctl >= 30.0:
        st, desc = "🟡 中", "估值中枢合理，性价比适中"
    else:
        st, desc = "🔴 低", "股票吸引力偏弱，注意防御"
    return (
        f"| 真实估值 (相对债券) | 股债比 EY/BY (沪深300) | {val:.2f}x | {pctl:.0f}% | {st} {desc} |"
    )


def _render_all_m_row(all_m: dict[str, Any]) -> str:
    val = all_m.get("pb_ew", 0.0)
    pctl = all_m.get("pb_percentile_10y", 0.0)
    if pctl >= 75.0:
        st, desc = "🔴 偏高", "全 A 整体估值具备一定溢价"
    elif pctl >= 55.0:
        st, desc = "🟡 中枢偏上", "估值中枢偏上，全 A 非全面低估"
    elif pctl >= 30.0:
        st, desc = "🟢 中枢合理", "资产估值处于历史中枢带"
    else:
        st, desc = "🟢 偏低", "全 A 资产深度折价，安全边际高"
    return (
        f"| 真实估值 (全 A 资产) | 全 A 水位 (中证全指 PB) | {val:.2f}x | "
        f"{pctl:.0f}% | {st} {desc} |"
    )


def _render_buf_row(buffett: dict[str, Any]) -> str:
    val = buffett.get("securitization_ratio", 0.0)
    pctl = buffett.get("percentile_10y", 0.0)
    if pctl >= 85.0:
        st, desc = "🟡 偏高", "规模高位，受超低利率与扩容推升"
    elif pctl >= 70.0:
        st, desc = "🟡 中偏高", "总市值相对 GDP 具备一定扩张"
    elif pctl >= 30.0:
        st, desc = "🟢 合理", "总市值与经济总量基本匹配"
    else:
        st, desc = "🟢 极低", "全市场总市值大幅折价"
    return f"| 宏观规模水位 | 证券化率 (市值/GDP) | {val:.1f}% | {pctl:.0f}% | {st} {desc} |"


def _render_breadth_row(breadth: dict[str, Any]) -> str:
    r20 = breadth.get("above_ma20_ratio", 0.0)
    if r20 > 80.0:
        st, desc = "🔴 过热", "短线亢奋，勿追高"
    elif r20 >= 40.0:
        st, desc = "🟢 健康", "短线处于常态健康带"
    else:
        st, desc = "⚪ 冰点", "短线悲观冰点，酝酿反弹"
    return f"| 短线情绪 | 站上 20 日线比例 | {r20:.0f}% | — | {st} {desc} |"


def _build_macro_signals_table(data: dict[str, Any]) -> list[str]:
    """构建宏观四维关键信号表格：区分真实估值、全 A 水位、宏观规模与短线情绪。"""
    macro = data.get("macro") or {}
    eyby = macro.get("ey_by") or {}
    all_m = macro.get("all_market") or {}
    buffett = macro.get("buffett") or {}
    breadth = data.get("breadth") or {}

    return [
        "## 四个关键信号",
        "| 类型 | 信号 | 关键数字 | 10年分位 | 说明 / 定性 |",
        "|---|---|---|---|---|",
        _render_eyby_row(eyby),
        _render_all_m_row(all_m),
        _render_buf_row(buffett),
        _render_breadth_row(breadth),
    ]


def _build_industry_selection(data: dict[str, Any]) -> list[str]:
    """构建行业怎么选板块。"""
    pbroe = data.get("pbroe") or {}
    tcr = data.get("tcr") or {}

    undervalued_raw = pbroe.get("undervalued_industries", [])
    undervalued = [_resolve_industry_name(c) for c in undervalued_raw[:4]]
    uv_text = "、".join(undervalued) if undervalued else "暂无显著偏离板块"

    top1_ind = _resolve_industry_name(tcr.get("top1_industry", "无"))
    top1_pct = tcr.get("top1_tcr", 0.0)
    crowded = [_resolve_industry_name(c) for c in tcr.get("crowded_industries", [])]

    if crowded:
        crowd_line = f"- 🔴 拥挤警戒：**{top1_ind}** 成交占 {top1_pct:.1f}%（>20% 警戒线）"
    else:
        crowd_line = f"- 🟢 拥挤警戒：全市场行业成交分布均衡（最高 {top1_ind} 占 {top1_pct:.1f}%）"

    return [
        "## 行业怎么选",
        f"- 🟢 低估洼地：**{uv_text}**（质优价廉）",
        crowd_line,
    ]


def _build_micro_health_line(data: dict[str, Any]) -> list[str]:
    """构建微观健康度分行指标。"""
    margin = data.get("margin") or {}
    breadth = data.get("breadth") or {}
    sentiment = data.get("sentiment") or {}

    m_ratio = margin.get("margin_penetration", 0.0)
    m_desc = "温和健康" if 2.2 <= m_ratio <= 2.8 else ("杠杆出清" if m_ratio < 2.2 else "杠杆偏热")

    pb_break = sentiment.get("pb_break_ratio", 0.0)
    pb_desc = "大面积折价" if pb_break > 7.0 else ("部分折价" if pb_break >= 4.0 else "常态区间")

    turnover = sentiment.get("turnover_ratio", 0.0)
    to_desc = "交易火热" if turnover > 6.0 else ("情绪适中" if turnover >= 3.0 else "交投低迷")

    r60 = breadth.get("above_ma60_ratio", 0.0)
    r60_desc = "多头走强" if r60 > 60.0 else ("修复中" if r60 >= 30.0 else "弱势寻底")

    return [
        "## 微观健康度",
        f"- 两融杠杆：**{m_ratio:.2f}%**（{m_desc}）",
        f"- 破净比例：**{pb_break:.2f}%**（{pb_desc}）",
        f"- 市场换手：**{turnover:.2f}%**（{to_desc}）",
        f"- 中期趋势：**{r60:.1f}%** 站上 60 日线（{r60_desc}）",
    ]


def _build_action_memo(data: dict[str, Any]) -> list[str]:
    """构建精简行动备忘清单。"""
    macro = data.get("macro") or {}
    pbroe = data.get("pbroe") or {}
    tcr = data.get("tcr") or {}

    exp_pct = macro.get("suggested_equity_exposure", 0.7) * 100
    exp_min = max(20, int(exp_pct - 10))
    exp_max = min(95, int(exp_pct + 10))

    undervalued_raw = pbroe.get("undervalued_industries", [])
    undervalued = [_resolve_industry_name(c) for c in undervalued_raw[:3]]
    uv_text = "、".join(undervalued) if undervalued else "低估核心资产"

    crowded = [_resolve_industry_name(c) for c in tcr.get("crowded_industries", [])]
    avoid_line = (
        f"- ❌ 不追{'/'.join(crowded)}等成交占比 >20% 的板块"
        if crowded
        else "- ❌ 不追短线涨幅过大的过热题材"
    )

    return [
        "## 操作备忘",
        f"- ✅ 保持 {exp_min}~{exp_max}% 仓位，定投低估宽基/高股息",
        f"- ✅ 回踩加仓{uv_text}",
        avoid_line,
        "- ❌ 不加高倍杠杆",
    ]


def format_investor_report(data: dict[str, Any]) -> str:
    """生成面向普通投资者清晰干练、一屏结论导向的每日体检报告。"""
    dt_str = data.get("trade_date", "")
    lines = [
        f"# 📈 A 股每日体检 · {dt_str}",
        "",
        "## 一句话结论",
        _build_one_sentence_summary(data),
        "",
    ]
    lines.extend(_build_macro_signals_table(data))
    lines.append("")
    lines.extend(_build_industry_selection(data))
    lines.append("")
    lines.extend(_build_micro_health_line(data))
    lines.append("")
    lines.extend(_build_action_memo(data))
    lines.append("")
    return "\n".join(lines)


def format_pro_report(data: dict[str, Any]) -> str:
    """生成面向专业量化与大模型对账审查的专业结构化 Markdown 报告。"""
    dt_str = data.get("trade_date", "")
    macro = data.get("macro") or {}
    eyby = macro.get("ey_by") or {}
    all_m = macro.get("all_market") or {}
    buffett = macro.get("buffett") or {}
    tcr = data.get("tcr") or {}
    pbroe = data.get("pbroe") or {}
    momentum = data.get("momentum") or {}
    margin = data.get("margin") or {}
    breadth = data.get("breadth") or {}
    sentiment = data.get("sentiment") or {}

    eyby_s = (
        f"{eyby.get('ey_by_ratio', 0.0):.2f}x (PE: {eyby.get('pe_ttm', 0.0):.2f}, "
        f"10Y: {eyby.get('bond_yield_10y', 0.0):.3f}%, "
        f"Pctl: {eyby.get('percentile_10y', 0.0):.1f}%)"
    )
    all_m_s = (
        f"PB: {all_m.get('pb_ew', 0.0):.3f} (Pctl: {all_m.get('pb_percentile_10y', 0.0):.1f}%), "
        f"PE: {all_m.get('pe_ttm_ew', 0.0):.2f} (Pctl: {all_m.get('pe_percentile_10y', 0.0):.1f}%)"
    )
    buf_s = (
        f"{buffett.get('securitization_ratio', 0.0):.1f}% (MV: "
        f"{buffett.get('total_market_cap_yi', 0.0):.0f}亿, "
        f"Pctl: {buffett.get('percentile_10y', 0.0):.1f}%)"
    )

    reg_desc = macro.get("regime_desc", "")
    lines = [
        f"# 📊 A 股量化全景体检专业报告 (基准日: {dt_str})",
        "",
        "---",
        "",
        f"## 1. 宏观周期与大类资产定价 (Macro Regime, As-Of: {macro.get('trade_date', dt_str)})",
        f"- **Regime**: `{macro.get('regime', 'NORMAL_ROTATION')}` ({reg_desc})",
        f"- **Exposure Limit**: `{macro.get('suggested_equity_exposure', 0.7) * 100:.1f}%`",
        f"- **EY/BY Ratio (000300)**: `{eyby_s}`",
        f"- **All-Market PB (000985)**: `{all_m_s}`",
        f"- **Buffett Ratio (MV/GDP)**: `{buf_s}`",
        "- **Key Drivers**:",
    ]
    for d in macro.get("key_drivers", []):
        lines.append(f"  - {d}")

    crowded = [_resolve_industry_name(c) for c in tcr.get("crowded_industries", [])]
    undervalued = [_resolve_industry_name(c) for c in pbroe.get("undervalued_industries", [])]
    t1_n = _resolve_industry_name(tcr.get("top1_industry", ""))
    t1_p = tcr.get("top1_tcr", 0.0)
    m_bal = margin.get("margin_balance_yi", 0.0)
    m_ratio = margin.get("margin_penetration", 0.0)
    m_dt = margin.get("trade_date", dt_str)

    b20 = breadth.get("above_ma20_ratio", 0.0)
    b60 = breadth.get("above_ma60_ratio", 0.0)
    b120 = breadth.get("above_ma120_ratio", 0.0)
    pbb = sentiment.get("pb_break_ratio", 0.0)
    to = sentiment.get("turnover_ratio", 0.0)

    p_alpha = pbroe.get("regression_alpha", 0.0)
    p_beta = pbroe.get("regression_beta", 0.0)
    p_r2 = pbroe.get("r_squared", 0.0)

    lines.extend(
        [
            "",
            (
                f"## 2. 中观行业轮动与风控 (TCR As-Of: {tcr.get('trade_date', dt_str)}, "
                f"PB-ROE As-Of: {pbroe.get('trade_date', dt_str)})"
            ),
            f"- **Total Amount**: `{tcr.get('total_amount_yi', 0.0):.1f} 亿元`",
            f"- **Top 1 Industry**: `{t1_n}` ({t1_p:.1f}%)",
            f"- **Crowded Industries**: `{crowded}`",
            f"- **PB-ROE Fit**: `R²={p_r2:.3f} (α: {p_alpha:.3f}, β: {p_beta:.4f})`",
            f"- **Undervalued Industries**: `{undervalued}`",
            f"- **Momentum Spread**: `{momentum.get('spread', 0.0):.1f}%`",
            "",
            f"## 3. 微观博弈与流动性情绪 (Margin As-Of: {m_dt})",
            f"- **Margin Penetration**: `{m_ratio:.2f}%` (Balance: {m_bal:.1f} 亿)",
            f"- **Breadth**: MA20 `{b20:.1f}%` | MA60 `{b60:.1f}%` | MA120 `{b120:.1f}%`",
            f"- **Sentiment**: PB Break `{pbb:.2f}%` | Turnover `{to:.2f}%`",
            "",
        ]
    )
    return "\n".join(lines)


def format_card_summary(data: dict[str, Any]) -> str:
    """生成终端控制台紧凑卡片输出。"""
    dt = data.get("trade_date", "")
    macro = data.get("macro") or {}
    regime = macro.get("regime", "NORMAL_ROTATION")
    _, regime_cn, advice = _get_regime_advice(regime)
    exp = macro.get("suggested_equity_exposure", 0.7) * 100

    tcr = data.get("tcr") or {}
    margin = data.get("margin") or {}

    top1 = _resolve_industry_name(tcr.get("top1_industry", "无"))
    tcr_p = tcr.get("top1_tcr", 0.0)
    m_pen = margin.get("margin_penetration", 0.0)

    lines = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        f"║  A 股量化体检全景摘要 ({dt})                                    ║",
        "╠══════════════════════════════════════════════════════════════════════╣",
        f"║  宏观周期: {regime_cn:<45} ║",
        f"║  建议仓位: {exp:>5.1f}%  |  实操: {advice[:28]:<34} ║",
        f"║  行业热点: {top1} (占比 {tcr_p:.1f}%)  |  两融渗透率: {m_pen:.2f}%           ║",
        "╚══════════════════════════════════════════════════════════════════════╝",
    ]
    return "\n".join(lines)


# 控制台报告格式化别名
format_console_report = format_card_summary
