"""量化扫描研判逻辑与信号构建辅助器 (Market Scan Evaluators)。"""

from __future__ import annotations

from typing import Any

from stock.analytics.models import (
    MacroRegimeResult,
    MacroSignalItem,
    MarketBreadthResult,
    MarketSentimentResult,
    MicroHealthSummary,
    ScanEvaluatorConfig,
)


def evaluate_one_sentence_summary(
    macro: MacroRegimeResult | None,
    undervalued: list[str],
    crowded: list[str],
    config: ScanEvaluatorConfig | None = None,
) -> str:
    """构建一句话核心决策结论。"""
    cfg = config or ScanEvaluatorConfig()
    uv_str = "/".join(undervalued[:3]) if undervalued else "低估高股息"
    crowd_str = "/".join(crowded[:2]) if crowded else "高位题材"

    if macro is None:
        return (
            f"微观情绪与行业结构分化明显。"
            f"**建议保持均衡标准配置，优选低估资产（{uv_str}），回避过热板块（{crowd_str}）。**"
        )

    eyby = macro.ey_by
    all_m = macro.all_market
    buffett = macro.buffett

    eyby_val = eyby.ey_by_ratio if eyby else 0.0
    eyby_pctl = eyby.percentile_10y if eyby else 0.0
    pb_pctl = all_m.pb_percentile_10y if all_m else 50.0
    buf_pctl = buffett.percentile_10y if buffett else 0.0
    exp_pct = macro.suggested_equity_exposure * 100

    if eyby_pctl >= cfg.eyby_high_pctl and (
        buf_pctl >= cfg.buffett_high_pctl or pb_pctl > cfg.pb_high_pctl
    ):
        return (
            f"股票性价比处于历史高位（沪深300 股债比 {eyby_val:.2f}x，"
            f"10 年 {eyby_pctl:.0f}% 分位），"
            f"但全 A 水位处于 {pb_pctl:.0f}% 中枢偏上，证券化率达 {buf_pctl:.0f}% 高分位——"
            f"便宜主要靠超低国债利率与大盘蓝筹，全 A 并非全面低估。"
            f"**保持 {exp_pct:.0f}% 仓位，只买便宜好货（{uv_str}），回避过热板块（{crowd_str}）。**"
        )
    if eyby_pctl >= cfg.eyby_high_pctl:
        return (
            f"股票资产处于高性价比战略建仓期（股债比 {eyby_val:.2f}x，"
            f"10 年 {eyby_pctl:.0f}% 分位）。"
            f"**保持 {exp_pct:.0f}% 积极仓位，重点配置质优价廉资产（{uv_str}）。**"
        )
    if eyby_pctl < cfg.eyby_low_pctl or buf_pctl >= cfg.buffett_extreme_pctl:
        return (
            f"市场估值与杠杆处于偏热风险区。"
            f"**建议将仓位严格控制在 {exp_pct:.0f}% 防御水平，坚决避险。**"
        )
    return (
        f"宏观估值处于常态中枢区间，无系统性风险。"
        f"**建议维持 {exp_pct:.0f}% 标准配置，优选 {uv_str}。**"
    )


def _build_eyby_signal(
    macro: MacroRegimeResult | None,
    config: ScanEvaluatorConfig | None = None,
) -> MacroSignalItem | None:
    cfg = config or ScanEvaluatorConfig()
    eyby = macro.ey_by if macro else None
    if not eyby:
        return None
    pctl = eyby.percentile_10y
    if pctl >= cfg.eyby_high_pctl:
        st, desc = "🟢 高", f"历史性机会，仅 {100 - pctl:.0f}% 时间更便宜"
    elif pctl >= cfg.eyby_low_pctl:
        st, desc = "🟡 中", "估值中枢合理，性价比适中"
    else:
        st, desc = "🔴 低", "股票吸引力偏弱，注意防御"
    return MacroSignalItem(
        category="真实估值 (相对债券)",
        name="股债比 EY/BY (沪深300)",
        value_str=f"{eyby.ey_by_ratio:.2f}x",
        percentile_str=f"{pctl:.0f}%",
        status=st,
        description=desc,
    )


def _build_all_m_signal(
    macro: MacroRegimeResult | None,
    config: ScanEvaluatorConfig | None = None,
) -> MacroSignalItem | None:
    cfg = config or ScanEvaluatorConfig()
    all_m = macro.all_market if macro else None
    if not all_m:
        return None
    pctl = all_m.pb_percentile_10y
    if pctl >= cfg.pb_extreme_high_pctl:
        st, desc = "🔴 偏高", "全 A 整体估值具备一定溢价"
    elif pctl >= cfg.pb_mid_high_pctl:
        st, desc = "🟡 中枢偏上", "估值中枢偏上，全 A 非全面低估"
    elif pctl >= cfg.pb_reasonable_pctl:
        st, desc = "🟢 中枢合理", "资产估值处于历史中枢带"
    else:
        st, desc = "🟢 偏低", "全 A 资产深度折价，安全边际高"
    return MacroSignalItem(
        category="真实估值 (全 A 资产)",
        name="全 A 水位 (中证全指 PB)",
        value_str=f"{all_m.pb_ew:.2f}x",
        percentile_str=f"{pctl:.0f}%",
        status=st,
        description=desc,
    )


def _build_buffett_signal(
    macro: MacroRegimeResult | None,
    config: ScanEvaluatorConfig | None = None,
) -> MacroSignalItem | None:
    cfg = config or ScanEvaluatorConfig()
    buf = macro.buffett if macro else None
    if not buf:
        return None
    pctl = buf.percentile_10y
    if pctl >= cfg.buffett_high_pctl:
        st, desc = "🟡 偏高", "规模高位，受超低利率与扩容推升"
    elif pctl >= cfg.buffett_mid_high_pctl:
        st, desc = "🟡 中偏高", "总市值相对 GDP 具备一定扩张"
    elif pctl >= cfg.buffett_reasonable_pctl:
        st, desc = "🟢 合理", "总市值与经济总量基本匹配"
    else:
        st, desc = "🟢 极低", "全市场总市值大幅折价"
    return MacroSignalItem(
        category="宏观规模水位",
        name="证券化率 (市值/GDP)",
        value_str=f"{buf.securitization_ratio:.1f}%",
        percentile_str=f"{pctl:.0f}%",
        status=st,
        description=desc,
    )


def _build_breadth_signal(
    breadth: MarketBreadthResult | None,
    config: ScanEvaluatorConfig | None = None,
) -> MacroSignalItem | None:
    if not breadth:
        return None
    cfg = config or ScanEvaluatorConfig()
    r20 = breadth.above_ma20_ratio
    if r20 > cfg.above_ma20_hot:
        st, desc = "🔴 过热", "短线亢奋，勿追高"
    elif r20 >= cfg.above_ma20_healthy:
        st, desc = "🟢 健康", "短线处于常态健康带"
    else:
        st, desc = "⚪ 冰点", "短线悲观冰点，酝酿反弹"
    return MacroSignalItem(
        category="短线情绪",
        name="站上 20 日线比例",
        value_str=f"{r20:.0f}%",
        percentile_str="—",
        status=st,
        description=desc,
    )


def build_signals(
    macro: MacroRegimeResult | None,
    breadth: MarketBreadthResult | None,
    config: ScanEvaluatorConfig | None = None,
) -> list[MacroSignalItem]:
    """生成宏观与微观信号列表。"""
    cfg = config or ScanEvaluatorConfig()
    signals: list[MacroSignalItem] = []
    for item in [
        _build_eyby_signal(macro, cfg),
        _build_all_m_signal(macro, cfg),
        _build_buffett_signal(macro, cfg),
        _build_breadth_signal(breadth, cfg),
    ]:
        if item is not None:
            signals.append(item)
    return signals


def evaluate_micro_health(
    margin_res: Any,
    sentiment_res: MarketSentimentResult | None,
    breadth_res: MarketBreadthResult | None,
    config: ScanEvaluatorConfig | None = None,
) -> MicroHealthSummary:
    """评估微观健康度状态。"""
    cfg = config or ScanEvaluatorConfig()
    m_ratio = margin_res.margin_penetration if margin_res else 0.0
    m_desc = (
        "温和健康"
        if cfg.margin_healthy_min <= m_ratio <= cfg.margin_healthy_max
        else ("杠杆出清" if m_ratio < cfg.margin_healthy_min else "杠杆偏热")
    )

    pb_break = sentiment_res.pb_break_ratio if sentiment_res else 0.0
    pb_desc = (
        "大面积折价"
        if pb_break > cfg.pb_break_warning
        else ("部分折价" if pb_break >= cfg.pb_break_moderate else "常态区间")
    )

    turnover = sentiment_res.turnover_ratio if sentiment_res else 0.0
    to_desc = (
        "交易火热"
        if turnover > cfg.turnover_hot
        else ("情绪适中" if turnover >= cfg.turnover_moderate else "交投低迷")
    )

    r60 = breadth_res.above_ma60_ratio if breadth_res else 0.0
    r60_desc = (
        "多头走强"
        if r60 > cfg.above_ma60_bull
        else ("修复中" if r60 >= cfg.above_ma60_repair else "弱势寻底")
    )

    return MicroHealthSummary(
        margin_ratio=round(m_ratio, 2),
        margin_status=m_desc,
        pb_break_ratio=round(pb_break, 2),
        pb_break_status=pb_desc,
        turnover_ratio=round(turnover, 2),
        turnover_status=to_desc,
        above_ma60_ratio=round(r60, 1),
        ma60_status=r60_desc,
    )


def build_action_items(
    macro: MacroRegimeResult | None,
    undervalued: list[str],
    crowded: list[str],
    config: ScanEvaluatorConfig | None = None,
) -> list[str]:
    """生成精简操作备忘清单。"""
    cfg = config or ScanEvaluatorConfig()
    exp_pct = (macro.suggested_equity_exposure if macro else cfg.default_equity_exposure) * 100
    exp_min = max(cfg.exposure_min_bound, int(exp_pct - cfg.exposure_buffer_pct))
    exp_max = min(cfg.exposure_max_bound, int(exp_pct + cfg.exposure_buffer_pct))

    uv_text = "、".join(undervalued[:3]) if undervalued else "低估核心资产"
    avoid_line = (
        f"- ❌ 不追{'/'.join(crowded)}等成交占比 >20% 的板块"
        if crowded
        else "- ❌ 不追短线涨幅过大的过热题材"
    )

    return [
        f"- ✅ 保持 {exp_min}~{exp_max}% 仓位，定投低估宽基/高股息",
        f"- ✅ 回踩加仓{uv_text}",
        avoid_line,
        "- ❌ 不加高倍杠杆",
    ]
