"""中观产业量化打分引擎、行业原型自适应与 PB-ROE 象限分类。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock_analytics.pipelines.industry_diagnostics.config import (
    ArchetypeConfig,
    IndustryThresholdsConfig,
    VetoRulesConfig,
)
from stock_analytics.pipelines.industry_diagnostics.types import IndustryScoreBreakdown

if TYPE_CHECKING:
    from stock_analytics.pipelines.industry_diagnostics.types import (
        IndustryConstituentsSnapshot,
        IndustryFinancialsSnapshot,
        IndustryTechnicalsSnapshot,
        IndustryValuationSnapshot,
    )


def calculate_momentum_score(
    technicals: IndustryTechnicalsSnapshot,
    thresholds: IndustryThresholdsConfig | None = None,
) -> float:
    """计算动量指标得分 (0~100)，阈值与偏离度限制配置驱动。"""
    t_cfg = thresholds or IndustryThresholdsConfig()
    score = 50.0
    close = technicals.close
    ma20 = technicals.ma20
    ma60 = technicals.ma60
    rsi = technicals.rsi14

    if ma20 is not None and ma60 is not None and close > 0:
        if close >= ma20 >= ma60:
            score = 80.0
            # 偏离均线幅度微调
            bias = (close - ma20) / ma20 * 100.0
            limit = t_cfg.momentum_bias_limit
            score += min(max(bias, -limit), limit)
        elif close <= ma20 <= ma60:
            score = 20.0
            bias = (close - ma20) / ma20 * 100.0
            limit = t_cfg.momentum_bias_limit
            score += min(max(bias, -limit), limit)
        elif close >= ma20:
            score = 55.0
        else:
            score = 45.0

    if rsi is not None:
        if rsi >= t_cfg.rsi_overbought:
            score -= 5.0  # 超买防冲高回落
        elif rsi <= t_cfg.rsi_oversold:
            score += 5.0  # 超卖反弹潜力

    return round(min(max(score, 0.0), 100.0), 1)


def calculate_valuation_score(
    valuation: IndustryValuationSnapshot,
    archetype: ArchetypeConfig | None = None,
) -> float:
    """计算估值赔率得分 (0~100)，PE/PB 权重由行业原型配置驱动。"""
    arch = archetype or ArchetypeConfig()
    pe_p = valuation.pe_percentile_5y
    pb_p = valuation.pb_percentile_5y

    if pe_p is None and pb_p is None:
        return 50.0

    pb_w = arch.valuation_weights.pb_weight
    pe_w = arch.valuation_weights.pe_weight

    if pb_p is not None and pe_p is not None:
        effective_percentile = pb_p * pb_w + pe_p * pe_w
    elif pb_p is not None:
        effective_percentile = pb_p
    else:
        effective_percentile = pe_p or 50.0

    val_score = 100.0 - effective_percentile

    # 股息利差安全垫加分 (正利差提供估值缓冲)
    if valuation.dividend_spread_10y is not None and valuation.dividend_spread_10y > 0:
        val_score += min(valuation.dividend_spread_10y * 5.0, 10.0)

    return round(min(max(val_score, 0.0), 100.0), 1)


def calculate_fundamental_score(
    financials: IndustryFinancialsSnapshot,
    thresholds: IndustryThresholdsConfig | None = None,
) -> float:
    """计算基本面质量与供需剪刀差得分 (0~100)，阶梯阈值由配置驱动。"""
    t_cfg = thresholds or IndustryThresholdsConfig()
    score = 50.0
    roe = financials.roe_avg
    np_yoy = financials.netprofit_yoy
    rev_yoy = financials.revenue_yoy
    scissors = financials.profit_scissors

    # 1. ROE 阶梯打分
    if roe is not None:
        if roe >= t_cfg.roe_high:
            score += 25.0
        elif roe >= t_cfg.roe_mid:
            score += 15.0
        elif roe >= t_cfg.roe_low:
            score += 0.0
        else:
            score -= 15.0

    # 2. 增长与供需剪刀差打分 (净利 YoY vs 营收 YoY)
    if np_yoy is not None and rev_yoy is not None:
        calc_scissors = scissors if scissors is not None else (np_yoy - rev_yoy)
        if np_yoy > t_cfg.growth_fast and rev_yoy > 10.0:
            score += 15.0
        elif np_yoy < t_cfg.growth_slump and rev_yoy < -10.0:
            score -= 20.0

        if calc_scissors > t_cfg.scissors_positive:
            score += 5.0  # 利润弹性大于营收，毛利与议价权扩张
        elif calc_scissors < t_cfg.scissors_negative:
            score -= 5.0  # 增收不增利或成本端挤压
    elif np_yoy is not None:
        if np_yoy > 15.0:
            score += 10.0
        elif np_yoy < -15.0:
            score -= 15.0

    return round(min(max(score, 0.0), 100.0), 1)


def calculate_crowding_penalty(
    constituents: IndustryConstituentsSnapshot,
    turnover_p5y: float | None = None,
    overheat_threshold: float = 90.0,
    momentum_score: float = 50.0,
    thresholds: IndustryThresholdsConfig | None = None,
) -> float:
    """计算拥挤度与巨头绑架背离扣分 (0~30)，阈值配置驱动。"""
    t_cfg = thresholds or IndustryThresholdsConfig()
    penalty = 0.0
    cr5 = constituents.cr5_concentration
    above_ma20 = constituents.above_ma20_ratio

    # 1. 换手率历史分位过高 (抱团过热)
    if turnover_p5y is not None and turnover_p5y >= overheat_threshold:
        penalty += min((turnover_p5y - overheat_threshold) * 2.0, 20.0)

    # 2. 龙头极端集中 (CR5 超过阈值) 带来踩踏隐患
    if cr5 is not None and cr5 > t_cfg.cr5_crowded:
        penalty += 5.0

    # 3. 广度背离防范 (巨头掩护出货 / 指数涨但多数成份股破位)
    if above_ma20 is not None and momentum_score >= 60.0:
        if above_ma20 < t_cfg.breadth_severe_divergence:
            penalty += 8.0  # 严重微观结构恶化扣分
        elif above_ma20 < t_cfg.breadth_mild_divergence:
            penalty += 4.0

    return round(min(max(penalty, 0.0), 30.0), 1)


def classify_pb_roe_quadrant(
    roe: float | None,
    pb_p5y: float | None,
    pe_p5y: float | None,
    roe_mid_threshold: float = 10.0,
    val_mid_percentile: float = 50.0,
) -> str:
    """按 ROE 质地与估值分位数定位 PB-ROE 四象限。"""
    is_high_roe = (roe is not None and roe >= roe_mid_threshold) or roe is None
    val_percentile = pb_p5y if pb_p5y is not None else (pe_p5y if pe_p5y is not None else 50.0)
    is_low_val = val_percentile <= val_mid_percentile

    if is_high_roe and is_low_val:
        return "核心资产·高性价比 (高ROE/低估值)"
    if is_high_roe and not is_low_val:
        return "景气成长·估值饱满 (高ROE/高估值)"
    if not is_high_roe and is_low_val:
        return "周期底部·反转博弈 (低ROE/低估值)"
    return "高估陷阱·谨慎回避 (低ROE/高估值)"


def calculate_industry_scores(
    industry_name: str,
    technicals: IndustryTechnicalsSnapshot,
    valuation: IndustryValuationSnapshot,
    financials: IndustryFinancialsSnapshot,
    constituents: IndustryConstituentsSnapshot,
    archetype: ArchetypeConfig | None = None,
    thresholds: IndustryThresholdsConfig | None = None,
    veto_rules: VetoRulesConfig | None = None,
    turnover_p5y: float | None = None,
) -> IndustryScoreBreakdown:
    """执行中观产业多维打分、行业原型自适应与一票否决门禁。"""
    arch = archetype or ArchetypeConfig()
    t_cfg = thresholds or IndustryThresholdsConfig()
    v_rules = veto_rules or VetoRulesConfig()

    mom_score = calculate_momentum_score(technicals, thresholds=t_cfg)
    val_score = calculate_valuation_score(valuation, archetype=arch)
    fund_score = calculate_fundamental_score(financials, thresholds=t_cfg)
    crowd_penalty = calculate_crowding_penalty(
        constituents,
        turnover_p5y=turnover_p5y,
        overheat_threshold=v_rules.overheat_turnover_percentile,
        momentum_score=mom_score,
        thresholds=t_cfg,
    )

    # 动态应用该原型专属的四维评分权重
    weights = arch.score_weights
    raw_composite = (
        mom_score * weights.momentum
        + val_score * weights.valuation
        + fund_score * weights.fundamental
        - crowd_penalty * weights.crowding
    )
    composite = round(min(max(raw_composite, 0.0), 100.0), 1)

    # PB-ROE 四象限
    quadrant = classify_pb_roe_quadrant(
        financials.roe_avg,
        valuation.pb_percentile_5y,
        valuation.pe_percentile_5y,
    )

    # 一票否决检查
    veto_triggered = False
    veto_reasons: list[str] = []

    np_yoy = financials.netprofit_yoy
    rev_yoy = financials.revenue_yoy
    if np_yoy is not None and rev_yoy is not None:
        if np_yoy < v_rules.profit_decay_threshold and rev_yoy < v_rules.revenue_decay_threshold:
            veto_triggered = True
            veto_reasons.append(
                f"财务严重衰退一票否决: 净利润下滑({np_yoy:.1f}%)且营收萎缩({rev_yoy:.1f}%)"
            )

    if turnover_p5y is not None and turnover_p5y >= 95.0:
        veto_triggered = True
        veto_reasons.append(f"换手极端拥挤一票否决: 历史分位达 {turnover_p5y:.1f}%")

    if financials.veto_flag and financials.veto_reason:
        veto_triggered = True
        if financials.veto_reason not in veto_reasons:
            veto_reasons.append(financials.veto_reason)

    return IndustryScoreBreakdown(
        industry_type=arch.title,
        momentum_score=mom_score,
        valuation_score=val_score,
        fundamental_score=fund_score,
        crowding_penalty=crowd_penalty,
        composite_score=composite,
        quadrant=quadrant,
        veto_triggered=veto_triggered,
        veto_reasons=veto_reasons,
    )
