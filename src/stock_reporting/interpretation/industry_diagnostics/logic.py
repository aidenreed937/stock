"""中观产业与行业量化诊断解读逻辑。"""

from __future__ import annotations

from typing import Any


def evaluate_industry_technicals(
    close: float,
    ma20: float | None,
    ma60: float | None,
    rsi14: float | None,
) -> dict[str, Any]:
    """评估技术指标形态。"""
    if ma20 is not None and ma60 is not None and close > 0:
        if close >= ma20 >= ma60:
            trend_desc = "多头排列 (站上MA20/MA60，动量偏强)"
            status = "bullish"
        elif close <= ma20 <= ma60:
            trend_desc = "空头排列 (受制于MA20/MA60，动量偏弱)"
            status = "bearish"
        elif close >= ma20 and close < ma60:
            trend_desc = "超跌反弹 (站上MA20但受制于MA60)"
            status = "rebound"
        else:
            trend_desc = "震荡整理 (跌破MA20但高于MA60)"
            status = "consolidation"
    else:
        trend_desc = "数据不足以判断均线形态"
        status = "unknown"

    rsi_desc = "中性"
    if rsi14 is not None:
        if rsi14 >= 70:
            rsi_desc = "超买 (注意冲高回落)"
        elif rsi14 <= 30:
            rsi_desc = "超卖 (注意反弹机会)"

    return {
        "trend_description": trend_desc,
        "trend_status": status,
        "rsi_description": rsi_desc,
    }


def evaluate_industry_valuation(
    pe_5y: float | None,
    pb_5y: float | None,
    threshold_low: float = 20.0,
    threshold_fair: float = 40.0,
    threshold_neutral: float = 70.0,
) -> dict[str, Any]:
    """评估估值状态。"""
    if pe_5y is not None:
        if pe_5y <= threshold_low:
            val_status = "低估区间 (安全边际显著)"
            level = "opportunity"
        elif pe_5y <= threshold_fair:
            val_status = "估值偏低 (具备较好性价比)"
            level = "attractive"
        elif pe_5y <= threshold_neutral:
            val_status = "估值中性 (处于合理震荡中枢)"
            level = "neutral"
        else:
            val_status = "估值偏高 (处于历史较高分位)"
            level = "warning"
    else:
        val_status = "估值中性"
        level = "neutral"

    return {
        "valuation_status": val_status,
        "valuation_level": level,
    }


def evaluate_industry_scores_summary(scores: dict[str, Any]) -> dict[str, Any]:
    """对多维打分与一票否决进行综合定调。"""
    composite = float(scores.get("composite_score", 50.0))
    veto = bool(scores.get("veto_triggered", False))

    if veto:
        stance = "一票否决预警 (基本面或拥挤度严重恶化)"
        rating = "VETO"
    elif composite >= 75.0:
        stance = "强烈推荐超配 (动量与估值/基本面多维共振)"
        rating = "STRONG_BUY"
    elif composite >= 60.0:
        stance = "结构性超配 (具备景气度或估值优势)"
        rating = "OVERWEIGHT"
    elif composite >= 40.0:
        stance = "标配中性 (处于震荡中枢)"
        rating = "NEUTRAL"
    else:
        stance = "建议低配/回避 (弱势动量或高估压力)"
        rating = "UNDERWEIGHT"

    return {
        "composite_score": composite,
        "investment_stance": stance,
        "rating": rating,
        "quadrant": str(scores.get("quadrant", "合理估值·平稳资产")),
        "veto_reasons": scores.get("veto_reasons", []),
    }


def evaluate_industry_diagnostics(data: dict[str, Any]) -> dict[str, Any]:
    """对行业诊断全景快照进行综合业务解读。"""
    tech = data.get("technicals", {})
    val = data.get("valuation", {})
    scores = data.get("scores", {})

    close = float(tech.get("close", 0.0))
    ma20 = tech.get("ma20")
    ma60 = tech.get("ma60")
    rsi14 = tech.get("rsi14")

    tech_eval = evaluate_industry_technicals(close, ma20, ma60, rsi14)
    val_eval = evaluate_industry_valuation(val.get("pe_percentile_5y"), val.get("pb_percentile_5y"))
    scores_eval = evaluate_industry_scores_summary(scores)

    return {
        "technicals": tech_eval,
        "valuation": val_eval,
        "scores": scores_eval,
    }
