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


def _format_buffett_interpretation(buf_val: float, buf_pctl: float) -> str:
    """结合证券化率绝对值与10年历史分位数生成客观通俗解读。"""
    if buf_pctl >= 85.0:
        return (
            f"处于近10年 **{buf_pctl:.1f}% 极高分位** (偏热高位区)。"
            "全市场总市值相对经济总量扩张显著，整体已非便宜低估区，需警惕估值消化压力。"
        )
    if buf_pctl >= 70.0:
        return (
            f"处于近10年 **{buf_pctl:.1f}% 中高分位** (轻度偏高)。"
            "全市场具备一定估值溢价，需依靠盈利基本面增长消化估值。"
        )
    if buf_pctl >= 30.0:
        return (
            f"处于近10年 **{buf_pctl:.1f}% 历史中枢** (常态合理区)。"
            "总市值与经济总量基本匹配，未见明显系统性泡沫或整体低估。"
        )
    if buf_pctl >= 15.0:
        return (
            f"处于近10年 **{buf_pctl:.1f}% 偏低分位** (具备安全边际)。"
            "全市场总市值相对经济总量较为便宜，具备较好中长期配置性价比。"
        )
    return (
        f"处于近10年 **{buf_pctl:.1f}% 极端低估洼地** (历史大底)。"
        "全市场总市值相对经济总量大幅折价，具备极高长期战略配置价值。"
    )


def _format_margin_interpretation(zone_desc: str, ratio: float) -> str:
    """根据两融杠杆渗透率与区间描述生成对应通俗解读。"""
    if ratio < 2.2:
        return f"处于 **{zone_desc}**。杠杆充分出清，筹码结构纯净，无强平负反馈风险。"
    if ratio < 2.8:
        return f"处于 **{zone_desc}**。场内杠杆处于常态健康水平，既无爆仓风险也无过度投机。"
    if ratio <= 3.5:
        return f"处于 **{zone_desc}**。游资与杠杆资金博弈加剧，波动率开始放大。"
    return f"处于 **{zone_desc}**。杠杆盘极度拥挤，高度警惕大盘回调时诱发的被动平仓多杀多。"


def _build_investor_decision_table(info: dict[str, Any]) -> list[str]:
    """构建通俗版一分钟决策指南表格。"""
    r_cn, adv = info["regime_cn"], info["summary_advice"]
    exp, uv = info["exp_pct"], info["undervalued_text"]
    t1_ind, t1_pct, crowd = info["top1_ind"], info["top1_pct"], info["crowd_text"]
    row_t1 = f"| 🔥 **最热行业** | **{t1_ind} ({t1_pct:.1f}%)** | {crowd} |"
    return [
        "## 🚦 一分钟决策指南（核心结论）",
        "| 决策维度 | 当前状态 / 信号 | 通俗解读与实操建议 |",
        "| :--- | :--- | :--- |",
        f"| 🎯 **大盘总评** | **{r_cn}** | {adv} |",
        f"| 📊 **建议总仓位** | **{exp:.0f}% (配置上限)** | 保持中高仓位进攻或定投 |",
        f"| 🛡️ **性价比板块** | **{uv}** | PB-ROE 残差洼地 |",
        row_t1,
    ]


def _build_investor_macro_section(
    eyby: dict[str, Any], buffett: dict[str, Any], macro: dict[str, Any]
) -> list[str]:
    """构建宏观大势通俗分析段落。"""
    eyby_val = eyby.get("ey_by_ratio", 0.0)
    eyby_pctl = eyby.get("percentile_10y", 0.0)
    buf_val = buffett.get("securitization_ratio", 0.0)
    buf_pctl = buffett.get("percentile_10y", 0.0)
    buf_mv = buffett.get("total_market_cap_yi", 0.0)

    lines = [
        "## 一、宏观天时：现在买股票划算吗？（周期与性价比）",
        f"- 🌡️ **股债性价比标尺 (EY/BY)**: `{eyby_val:.2f}x`（10年分位: `{eyby_pctl:.1f}%`）",
        (
            f"  > 💡 **通俗解读**: 股票隐含收益率是 10 年期国债利率的 **{eyby_val:.2f} 倍**。"
            f" 历史上仅有约 {100 - eyby_pctl:.1f}% 的悲观大底才具备如此性价比，属于战略建仓期。"
        ),
        (
            f"- 🏛️ **证券化率 (巴菲特指标)**: `{buf_val:.1f}%`"
            f"（总市值约 `{buf_mv:.0f}` 亿，10年分位: `{buf_pctl:.1f}%`）"
        ),
        f"  > 💡 **通俗解读**: {_format_buffett_interpretation(buf_val, buf_pctl)}",
    ]
    for d in macro.get("key_drivers", []):
        if "分歧" in d:
            lines.append(f"- ⚠️ **{d}**")
    return lines


def _build_investor_industry_section(
    undervalued_text: str,
    top1_ind: str,
    top1_pct: float,
    crowd_text: str,
    momentum: dict[str, Any],
) -> list[str]:
    """构建中观行业通俗分析段落。"""
    mom_diag = momentum.get("diagnostics", "常态分化")
    return [
        "## 二、中观地利：哪些行业安全？哪些行业太热？（行业攻防地图）",
        "### 1. 🛡️ 最具性价比的“便宜好货”洼地 (PB-ROE 残差排序)",
        f"- 重点关注行业: **{undervalued_text}**",
        "  > 💡 **通俗解读**: 行业市净率低于 ROE 公允水平，属于质优价廉、被错杀的低估值资产。",
        "",
        "### 2. ⚠️ 资金拥挤度与轮动雷达",
        f"- **成交最火热行业**: `{top1_ind}` (单日占 31 行业总成交 `{top1_pct:.1f}%`)",
        f"- **极端拥挤度状态**: {crowd_text}",
        f"- **动量剪刀差**: `{momentum.get('spread', 0.0):.1f}%` ({mom_diag})",
    ]


def _build_investor_micro_section(
    margin: dict[str, Any],
    breadth: dict[str, Any],
    sentiment: dict[str, Any],
    dt_str: str,
) -> list[str]:
    """构建微观情绪通俗分析段落。"""
    m_ratio, m_bal = margin.get("margin_penetration", 0.0), margin.get("margin_balance_yi", 0.0)
    m_dt = margin.get("trade_date", dt_str)
    m_tag = f" (截至 {m_dt} T-1)" if m_dt and m_dt != dt_str else ""
    m_desc = margin.get("zone_desc", "正常")

    r20, r60 = breadth.get("above_ma20_ratio", 0.0), breadth.get("above_ma60_ratio", 0.0)
    r20_note = "(短线亢奋过热，慎防回踩)" if r20 > 80 else "(短线处于常态)"
    pb_break, turnover = sentiment.get("pb_break_ratio", 0.0), sentiment.get("turnover_ratio", 0.0)

    return [
        "## 三、微观人和：场内资金与情绪如何？（筹码与博弈健康度）",
        f"- 💰 **两融杠杆渗透率**: `{m_ratio:.2f}%` (两融余额约 `{m_bal:.0f}` 亿元{m_tag})",
        f"  > 💡 **通俗解读**: {_format_margin_interpretation(m_desc, m_ratio)}",
        "- 🧭 **全市场多周期宽度**:",
        f"  - **短线情绪 (站上 MA20 比例)**: `{r20:.1f}%` {r20_note}",
        f"  - **中期生命线 (站上 MA60 比例)**: `{r60:.1f}%` (中期趋势修复中)",
        "- 📉 **破净率与换手率**:",
        f"  - 全市场破净率 `{pb_break:.2f}%`（资产大面积折价）",
        f"  - 平均换手率 `{turnover:.2f}%`（活跃度适中）",
    ]


def _build_investor_memo() -> list[str]:
    """构建投资者实操备忘录。"""
    return [
        "## 四、普通投资者实操备忘录",
        "- ✅ **宜 (DO)**:",
        "  1. 维持中高仓位（70%~85%），坚定持有被低估的宽基指数与高股息核心资产；",
        "  2. 遇到盘中分歧回踩时，逢低加仓 PB-ROE 突出的低估值高性价比板块；",
        "  3. 采取分批定投策略，平滑持仓成本与心理波动。",
        "- ❌ **忌 (DON'T)**:",
        "  1. 切忌在战略大底区域过度悲观、空仓等待“绝对最低点”；",
        "  2. 切忌追涨单日成交占比 >20% 或短线涨幅过大的高拥挤度题材；",
        "  3. 切忌使用场外高倍杠杆博弈短线波动。",
    ]


def format_investor_report(data: dict[str, Any]) -> str:
    """生成面向普通投资者阅读体验良好的通俗白话版体检报告。"""
    dt_str = data.get("trade_date", "")
    macro = data.get("macro") or {}
    tcr = data.get("tcr") or {}
    pbroe = data.get("pbroe") or {}
    momentum = data.get("momentum") or {}
    margin = data.get("margin") or {}
    breadth = data.get("breadth") or {}
    sentiment = data.get("sentiment") or {}

    rating_badge, regime_cn, summary_advice = _get_regime_advice(
        macro.get("regime", "NORMAL_ROTATION")
    )
    exp_pct = macro.get("suggested_equity_exposure", 0.7) * 100

    top1_ind = _resolve_industry_name(tcr.get("top1_industry", "无"))
    top1_pct = tcr.get("top1_tcr", 0.0)
    crowded = [_resolve_industry_name(c) for c in tcr.get("crowded_industries", [])]
    crowd_text = f"⚠️ 极端拥挤行业: `{', '.join(crowded)}`" if crowded else "🟢 无极端拥挤行业"

    undervalued_raw = pbroe.get("undervalued_industries", [])
    undervalued = [_resolve_industry_name(c) for c in undervalued_raw[:4]]
    undervalued_text = ", ".join(undervalued) if undervalued else "暂无显著偏离行业"

    table_info = {
        "regime_cn": regime_cn,
        "summary_advice": summary_advice,
        "exp_pct": exp_pct,
        "undervalued_text": undervalued_text,
        "top1_ind": top1_ind,
        "top1_pct": top1_pct,
        "crowd_text": crowd_text,
    }

    eyby_dict = macro.get("ey_by") or {}
    buf_dict = macro.get("buffett") or {}

    lines = [
        "# 📈 A 股量化每日体检报告（投资者通俗版）",
        f"> **体检基准日**: {dt_str} | **综合评级**: {rating_badge}",
        "",
        "---",
        "",
    ]
    lines.extend(_build_investor_decision_table(table_info))
    lines.extend(["", "---", ""])
    lines.extend(_build_investor_macro_section(eyby_dict, buf_dict, macro))
    lines.extend(["", "---", ""])
    lines.extend(
        _build_investor_industry_section(undervalued_text, top1_ind, top1_pct, crowd_text, momentum)
    )
    lines.extend(["", "---", ""])
    lines.extend(_build_investor_micro_section(margin, breadth, sentiment, dt_str))
    lines.extend(["", "---", ""])
    lines.extend(_build_investor_memo())
    lines.append("")
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

    reg_desc = macro.get("regime_desc", "")
    lines = [
        f"# 📊 A 股量化全景体检专业报告 (基准日: {dt_str})",
        "",
        "---",
        "",
        f"## 1. 宏观周期与大类资产定价 (Macro Regime, As-Of: {macro.get('trade_date', dt_str)})",
        f"- **Regime**: `{macro.get('regime', 'NORMAL_ROTATION')}` ({reg_desc})",
        f"- **Exposure Limit**: `{macro.get('suggested_equity_exposure', 0.7) * 100:.1f}%`",
        f"- **EY/BY Ratio**: `{eyby_s}`",
        f"- **Buffett Ratio**: `{buf_s}`",
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
