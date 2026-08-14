"""量化体检报告格式化器 (支持普通投资者通俗版、专业量化版与终端控制台卡片)。"""

from __future__ import annotations

from typing import Any, Final

from stock.analytics.industry.classifier import IndustryClassifier

# 宏观周期状态中文名称映射表
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


def format_investor_report(data: dict[str, Any]) -> str:
    """生成面向普通投资者阅读体验良好的通俗白话版体检报告。"""
    dt_str = data.get("trade_date", "")
    macro = data.get("macro") or {}
    eyby = macro.get("ey_by") or {}
    buffett = macro.get("buffett") or {}
    tcr = data.get("tcr") or {}
    pbroe = data.get("pbroe") or {}
    momentum = data.get("momentum") or {}
    margin = data.get("margin") or {}
    breadth = data.get("breadth") or {}
    sentiment = data.get("sentiment") or {}

    regime = macro.get("regime", "NORMAL_ROTATION")
    exp_pct = macro.get("suggested_equity_exposure", 0.7) * 100
    rating_badge, regime_cn, summary_advice = _get_regime_advice(regime)

    eyby_val = eyby.get("ey_by_ratio", 0.0)
    eyby_pctl = eyby.get("percentile_10y", 0.0)
    buf_val = buffett.get("securitization_ratio", 0.0)
    buf_mv = buffett.get("total_market_cap_yi", 0.0)

    top1_ind = _resolve_industry_name(tcr.get("top1_industry", "无"))
    top1_pct = tcr.get("top1_tcr", 0.0)
    crowded = [_resolve_industry_name(c) for c in tcr.get("crowded_industries", [])]
    crowd_text = f"⚠️ 极端拥挤行业: `{', '.join(crowded)}`" if crowded else "🟢 无极端拥挤行业"

    undervalued_raw = pbroe.get("undervalued_industries", [])
    undervalued = [_resolve_industry_name(c) for c in undervalued_raw[:4]]
    undervalued_text = ", ".join(undervalued) if undervalued else "暂无显著偏离行业"

    m_ratio = margin.get("margin_penetration", 0.0)
    m_bal = margin.get("margin_balance_yi", 0.0)
    m_dt = margin.get("trade_date", dt_str)
    m_tag = f" (截至 {m_dt} T-1)" if m_dt and m_dt != dt_str else ""

    r20 = breadth.get("above_ma20_ratio", 0.0)
    r60 = breadth.get("above_ma60_ratio", 0.0)
    pb_break = sentiment.get("pb_break_ratio", 0.0)
    turnover = sentiment.get("turnover_ratio", 0.0)

    r20_note = "(短线亢奋过热，慎防回踩)" if r20 > 80 else "(短线处于常态)"
    mom_diag = momentum.get("diagnostics", "常态分化")

    lines = [
        "# 📈 A 股量化每日体检报告（投资者通俗版）",
        f"> **体检基准日**: {dt_str} | **综合评级**: {rating_badge}",
        "",
        "---",
        "",
        "## 🚦 一分钟决策指南（核心结论）",
        "| 决策维度 | 当前状态 / 信号 | 通俗解读与实操建议 |",
        "| :--- | :--- | :--- |",
        f"| 🎯 **大盘总评** | **{regime_cn}** | {summary_advice} |",
        f"| 📊 **建议总仓位** | **{exp_pct:.0f}% (配置上限)** | 维持中高仓位进攻或积极定投 |",
        f"| 🛡️ **最具性价比板块** | **{undervalued_text}** | PB-ROE 残差低估洼地，极高性价比 |",
        f"| 🔥 **最活跃行业** | **{top1_ind} ({top1_pct:.1f}%)** | {crowd_text} |",
        "",
        "---",
        "",
        "## 一、宏观天时：现在买股票划算吗？（周期与性价比）",
        f"- 🌡️ **股债性价比标尺 (EY/BY)**: `{eyby_val:.2f}x`（10年分位: `{eyby_pctl:.1f}%`）",
        f"  > 💡 **通俗解读**: 股票隐含收益率是 10 年期国债利率的 **{eyby_val:.2f} 倍**。"
        f" 历史上仅有约 {100 - eyby_pctl:.1f}% 的悲观大底才具备如此性价比，属于战略建仓期。",
        f"- 🏛️ **证券化率 (巴菲特指标)**: `{buf_val:.1f}%`（A 股总市值约 `{buf_mv:.0f}` 亿元）",
        "  > 💡 **通俗解读**: 全市场总市值与经济 GDP 总量匹配，估值健康，未见脱离基本面的泡沫。",
    ]

    for d in macro.get("key_drivers", []):
        if "分歧" in d:
            lines.append(f"- ⚠️ **{d}**")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 二、中观地利：哪些行业安全？哪些行业太热？（行业攻防地图）",
            "### 1. 🛡️ 最具性价比的“便宜好货”洼地 (PB-ROE 残差排序)",
            f"- 重点关注行业: **{undervalued_text}**",
            "  > 💡 **通俗解读**: 行业市净率低于 ROE 公允水平，属于质优价廉、被错杀的低估值资产。",
            "",
            "### 2. ⚠️ 资金拥挤度与轮动雷达",
            f"- **成交最火热行业**: `{top1_ind}` (单日占 31 行业总成交 `{top1_pct:.1f}%`)",
            f"- **极端拥挤度状态**: {crowd_text}",
            f"- **动量剪刀差**: `{momentum.get('spread', 0.0):.1f}%` ({mom_diag})",
            "",
            "---",
            "",
            "## 三、微观人和：场内资金与情绪如何？（筹码与博弈健康度）",
            f"- 💰 **两融杠杆渗透率**: `{m_ratio:.2f}%` (两融余额约 `{m_bal:.0f}` 亿元{m_tag})",
            (
                f"  > 💡 **通俗解读**: 处于 **{margin.get('zone_desc', '正常')}**。"
                " 杠杆充分出清，无踩踏爆仓风险。"
            ),
            "- 🧭 **全市场多周期宽度**:",
            f"  - **短线情绪 (站上 MA20 比例)**: `{r20:.1f}%` {r20_note}",
            f"  - **中期生命线 (站上 MA60 比例)**: `{r60:.1f}%` (中期趋势修复中)",
            "- 📉 **破净率与换手率**:",
            f"  - 全市场破净率 `{pb_break:.2f}%`（资产大面积折价）",
            f"  - 平均换手率 `{turnover:.2f}%`（活跃度适中）",
            "",
            "---",
            "",
            "## 四、普通投资者实操备忘录",
            "- ✅ **宜 (DO)**:",
            "  1. 维持中高仓位（70%~85%），坚定持有被低估的宽基指数与高股息核心资产；",
            "  2. 遇到盘中分歧回踩时，逢低加仓 PB-ROE 突出的低估值高性价比板块；",
            "  3. 采取分批定投策略，平滑持仓成本与心理波动。",
            "- ❌ **忌 (DON'T)**:",
            "  1. 切忌在战略大底区域过度悲观、空仓等待“绝对最低点”；",
            "  2. 切忌追涨单日成交占比 >20% 或短线涨幅过大的高拥挤度题材；",
            "  3. 切忌使用场外高倍杠杆博弈短线波动。",
            "",
        ]
    )
    return "\n".join(lines)


def format_pro_report(data: dict[str, Any]) -> str:
    """生成面向专业量化与大模型对账审查的专业结构化 Markdown 报告。"""
    dt_str = data.get("trade_date", "")
    macro = data.get("macro") or {}
    eyby = macro.get("ey_by") or {}
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
    buf_s = (
        f"{buffett.get('securitization_ratio', 0.0):.1f}% (MV: "
        f"{buffett.get('total_market_cap_yi', 0.0):.0f}亿, "
        f"Pctl: {buffett.get('percentile_10y', 0.0):.1f}%)"
    )
    pb_fit = (
        f"R²={pbroe.get('r_squared', 0.0):.3f} (α: {pbroe.get('regression_alpha', 0.0):.3f}, "
        f"β: {pbroe.get('regression_beta', 0.0):.4f})"
    )

    tcr_dt = tcr.get("trade_date", dt_str)
    margin_dt = margin.get("trade_date", dt_str)
    pbroe_dt = pbroe.get("trade_date", dt_str)

    lines = [
        f"# 📊 A 股量化全景体检专业报告 (基准日: {dt_str})",
        "",
        "---",
        "",
        f"## 1. 宏观周期与大类资产定价 (Macro Regime, As-Of: {macro.get('trade_date', dt_str)})",
        f"- **Regime**: `{macro.get('regime', 'UNKNOWN')}` ({macro.get('regime_desc', '')})",
        f"- **Exposure Limit**: `{macro.get('suggested_equity_exposure', 0.0) * 100:.1f}%`",
        f"- **EY/BY Ratio**: `{eyby_s}`",
        f"- **Buffett Ratio**: `{buf_s}`",
        "- **Key Drivers**:",
    ]
    for d in macro.get("key_drivers", []):
        lines.append(f"  - {d}")

    ind_title = f"## 2. 中观行业轮动与风控 (TCR As-Of: {tcr_dt}, PB-ROE As-Of: {pbroe_dt})"
    lines.extend(
        [
            "",
            ind_title,
            f"- **Total Amount**: `{tcr.get('total_amount_yi', 0.0):.1f} 亿元`",
            f"- **Top 1 Industry**: `{tcr.get('top1_industry', '')}` "
            f"({tcr.get('top1_tcr', 0.0):.1f}%)",
            f"- **Crowded Industries**: `{tcr.get('crowded_industries', [])}`",
            f"- **PB-ROE Fit**: `{pb_fit}`",
            f"- **Undervalued Industries**: `{pbroe.get('undervalued_industries', [])}`",
            f"- **Momentum Spread**: `{momentum.get('spread', 0.0):.1f}%`",
            "",
            f"## 3. 微观博弈与流动性情绪 (Micro Sentiment, Margin As-Of: {margin_dt})",
            f"- **Margin Penetration**: `{margin.get('margin_penetration', 0.0):.2f}%` "
            f"(Balance: {margin.get('margin_balance_yi', 0.0):.1f} 亿)",
            f"- **Breadth**: MA20 `{breadth.get('above_ma20_ratio', 0.0):.1f}%` | "
            f"MA60 `{breadth.get('above_ma60_ratio', 0.0):.1f}%` | "
            f"MA120 `{breadth.get('above_ma120_ratio', 0.0):.1f}%`",
            f"- **Sentiment**: PB Break `{sentiment.get('pb_break_ratio', 0.0):.2f}%` | "
            f"Turnover `{sentiment.get('turnover_ratio', 0.0):.2f}%`",
            "",
        ]
    )
    return "\n".join(lines)


def format_console_report(data: dict[str, Any]) -> str:
    """生成终端控制台友好的 ASCII 纯文本卡片报告。"""
    dt_str = data.get("trade_date", "")
    macro = data.get("macro") or {}
    eyby = macro.get("ey_by") or {}
    buffett = macro.get("buffett") or {}
    tcr = data.get("tcr") or {}
    pbroe = data.get("pbroe") or {}
    momentum = data.get("momentum") or {}
    margin = data.get("margin") or {}
    breadth = data.get("breadth") or {}
    sentiment = data.get("sentiment") or {}

    crowded = [_resolve_industry_name(c) for c in tcr.get("crowded_industries", [])]
    crowded_str = f"⚠️ {', '.join(crowded)}" if crowded else "🟢 无"
    undervalued_raw = pbroe.get("undervalued_industries", [])
    undervalued = [_resolve_industry_name(c) for c in undervalued_raw[:4]]
    undervalued_str = ", ".join(undervalued) if undervalued else "无"

    regime_key = macro.get("regime", "NORMAL_ROTATION")
    regime_str = REGIME_CN_NAMES.get(regime_key, "⚪ 常态结构轮动期")
    exposure_str = f"{macro.get('suggested_equity_exposure', 0.0) * 100:.1f}%"

    eyby_val = eyby.get("ey_by_ratio", 0.0)
    eyby_pctl = eyby.get("percentile_10y", 0.0)
    eyby_bond = eyby.get("bond_yield_10y", 0.0)

    buf_val = buffett.get("securitization_ratio", 0.0)
    buf_mv = buffett.get("total_market_cap_yi", 0.0)
    buf_pctl = buffett.get("percentile_10y", 0.0)

    tcr_amt = tcr.get("total_amount_yi", 0.0)
    tcr_top = _resolve_industry_name(tcr.get("top1_industry", "无"))
    tcr_top_pct = tcr.get("top1_tcr", 0.0)

    r2_val = pbroe.get("r_squared", 0.0)
    mom_val = momentum.get("spread", 0.0)

    m_ratio = margin.get("margin_penetration", 0.0)
    m_desc = margin.get("zone_desc", "")

    r20 = breadth.get("above_ma20_ratio", 0.0)
    r60 = breadth.get("above_ma60_ratio", 0.0)
    r120 = breadth.get("above_ma120_ratio", 0.0)
    pb_break = sentiment.get("pb_break_ratio", 0.0)
    turnover = sentiment.get("turnover_ratio", 0.0)

    b_str = f"MA20={r20:.1f}% | MA60={r60:.1f}% | MA120={r120:.1f}%"
    s_str = f"破净率={pb_break:.2f}% | 换手率={turnover:.2f}%"

    card = f"""
================================================================================
                    🇨🇳 A 股量化全景体检日报 ({dt_str})
================================================================================
[1] 宏观周期温度计 (Macro Regime)
  - 周期象限判定 : {regime_str}
  - 建议权益仓位 : {exposure_str}
  - 股债收益比   : {eyby_val:.2f}x (分位: {eyby_pctl:.1f}%, 10Y国债: {eyby_bond:.3f}%)
  - 证券化率     : {buf_val:.1f}% (总市值: {buf_mv:.0f}亿, 分位: {buf_pctl:.1f}%)

[2] 中观行业风控雷达 (Industry Radar)
  - 31 行业总成交 : {tcr_amt:.1f} 亿元 (Top 1: {tcr_top} {tcr_top_pct:.1f}%)
  - 极端拥挤行业 : {crowded_str}
  - PB-ROE 洼地  : {undervalued_str} (R²: {r2_val:.3f})
  - 动量剪刀差   : {mom_val:.1f}% ({momentum.get("diagnostics", "常态")})

[3] 微观博弈与情绪 (Micro Sentiment)
  - 两融杠杆渗透 : {m_ratio:.2f}% ({m_desc})
  - 多周期宽度   : {b_str}
  - 破净率/换手  : {s_str}
================================================================================
"""
    return card.strip()
