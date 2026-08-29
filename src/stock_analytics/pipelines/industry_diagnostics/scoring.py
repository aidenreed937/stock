"""中观产业量化打分引擎、周期属性自适应与 PB-ROE 象限分类。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stock_analytics.pipelines.industry_diagnostics.types import IndustryScoreBreakdown

if TYPE_CHECKING:
    from stock_analytics.pipelines.industry_diagnostics.config import (
        ScoreWeightsConfig,
        VetoRulesConfig,
    )
    from stock_analytics.pipelines.industry_diagnostics.types import (
        IndustryConstituentsSnapshot,
        IndustryFinancialsSnapshot,
        IndustryTechnicalsSnapshot,
        IndustryValuationSnapshot,
    )


# 申万行业五大属性映射字典 (用于针对性防范周期股与赛道股估值失真)
_CYCLICAL_KEYWORDS = (
    "煤炭",
    "钢铁",
    "有色",
    "化工",
    "建材",
    "石化",
    "航运",
    "水泥",
    "矿",
    "铝",
    "铜",
)
_CONSUMPTION_KEYWORDS = (
    "食品",
    "饮料",
    "白酒",
    "医药",
    "家电",
    "零售",
    "社服",
    "轻工",
    "美护",
    "纺织",
    "农业",
    "猪",
)
_TECH_KEYWORDS = ("电子", "半导体", "计算机", "通信", "传媒", "软件", "军工", "AI")
_MFG_KEYWORDS = ("电力设备", "新能源", "光伏", "电池", "机械", "汽车", "自动化", "制造")
_STABLE_KEYWORDS = (
    "银行",
    "证券",
    "保险",
    "非银",
    "公用",
    "电力",
    "交运",
    "港口",
    "铁路",
    "环保",
    "地产",
)


def resolve_industry_type(industry_name: str) -> str:
    """根据行业名称识别行业内在经济与周期属性。"""
    for kw in _CYCLICAL_KEYWORDS:
        if kw in industry_name:
            return "强周期资源与大宗"
    for kw in _CONSUMPTION_KEYWORDS:
        if kw in industry_name:
            return "大消费与核心资产"
    for kw in _TECH_KEYWORDS:
        if kw in industry_name:
            return "科技成长与创新"
    for kw in _MFG_KEYWORDS:
        if kw in industry_name:
            return "先进制造与新能源"
    for kw in _STABLE_KEYWORDS:
        if kw in industry_name:
            return "稳定红利与大金融"
    return "通用制造与消费"


def calculate_momentum_score(technicals: IndustryTechnicalsSnapshot) -> float:
    """计算动量指标得分 (0~100)。"""
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
            score += min(max(bias, -10.0), 10.0)
        elif close <= ma20 <= ma60:
            score = 20.0
            bias = (close - ma20) / ma20 * 100.0
            score += min(max(bias, -10.0), 10.0)
        elif close >= ma20:
            score = 55.0
        else:
            score = 45.0

    if rsi is not None:
        if rsi >= 75.0:
            score -= 5.0  # 超买防冲高回落
        elif rsi <= 25.0:
            score += 5.0  # 超卖反弹潜力

    return round(min(max(score, 0.0), 100.0), 1)


def calculate_valuation_score(
    valuation: IndustryValuationSnapshot,
    industry_type: str = "通用制造与消费",
) -> float:
    """计算估值赔率得分 (0~100，周期品以 PB 分位为主防范低 PE 陷阱)。"""
    pe_p = valuation.pe_percentile_5y
    pb_p = valuation.pb_percentile_5y

    if pe_p is None and pb_p is None:
        return 50.0

    # 针对强周期行业：以 PB 5Y 分位数为主 (权重 80%)，防范景气峰值低 PE 见顶陷阱
    if industry_type == "强周期资源与大宗":
        if pb_p is not None and pe_p is not None:
            effective_percentile = pb_p * 0.80 + pe_p * 0.20
        elif pb_p is not None:
            effective_percentile = pb_p
        else:
            effective_percentile = pe_p or 50.0
    else:
        valid_p = [p for p in (pe_p, pb_p) if p is not None]
        effective_percentile = sum(valid_p) / len(valid_p) if valid_p else 50.0

    val_score = 100.0 - effective_percentile

    # 股息利差安全垫加分
    if valuation.dividend_spread_10y is not None and valuation.dividend_spread_10y > 0:
        val_score += min(valuation.dividend_spread_10y * 5.0, 10.0)

    return round(min(max(val_score, 0.0), 100.0), 1)


def calculate_fundamental_score(financials: IndustryFinancialsSnapshot) -> float:
    """计算基本面质量与供需剪刀差得分 (0~100)。"""
    score = 50.0
    roe = financials.roe_avg
    np_yoy = financials.netprofit_yoy
    rev_yoy = financials.revenue_yoy
    scissors = financials.profit_scissors

    # 1. ROE 水位打分 (中枢按 10% 评估)
    if roe is not None:
        if roe >= 18.0:
            score += 25.0
        elif roe >= 12.0:
            score += 15.0
        elif roe >= 6.0:
            score += 0.0
        else:
            score -= 15.0

    # 2. 增长与供需剪刀差打分 (净利 YoY vs 营收 YoY)
    if np_yoy is not None and rev_yoy is not None:
        calc_scissors = scissors if scissors is not None else (np_yoy - rev_yoy)
        if np_yoy > 20.0 and rev_yoy > 10.0:
            score += 15.0
        elif np_yoy < -20.0 and rev_yoy < -10.0:
            score -= 20.0

        if calc_scissors > 5.0:
            score += 5.0  # 利润弹性大于营收，毛利与议价权扩张
        elif calc_scissors < -10.0:
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
) -> float:
    """计算拥挤度与巨头绑架背离扣分 (0~30)。"""
    penalty = 0.0
    cr5 = constituents.cr5_concentration
    above_ma20 = constituents.above_ma20_ratio

    # 1. 换手率/成交额占比历史分位过高 (抱团过热)
    if turnover_p5y is not None and turnover_p5y >= overheat_threshold:
        penalty += min((turnover_p5y - overheat_threshold) * 2.0, 20.0)

    # 2. 龙头极端集中 (CR5 > 80%) 带来抱团踩踏隐患
    if cr5 is not None and cr5 > 80.0:
        penalty += 5.0

    # 3. 广度背离防范 (巨头掩护出货 / 指数涨但 70% 成份股跌破均线)
    if above_ma20 is not None and momentum_score >= 60.0:
        if above_ma20 < 30.0:
            penalty += 8.0  # 严重微观结构恶化扣分
        elif above_ma20 < 45.0:
            penalty += 4.0

    return round(min(max(penalty, 0.0), 30.0), 1)


def classify_pb_roe_quadrant(
    roe: float | None,
    pb_p5y: float | None,
    pe_p5y: float | None,
) -> str:
    """按 ROE 质地与估值分位数定位 PB-ROE 四象限。"""
    is_high_roe = (roe is not None and roe >= 10.0) or roe is None
    val_percentile = pb_p5y if pb_p5y is not None else (pe_p5y if pe_p5y is not None else 50.0)
    is_low_val = val_percentile <= 50.0

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
    weights: ScoreWeightsConfig,
    veto_rules: VetoRulesConfig,
    turnover_p5y: float | None = None,
) -> IndustryScoreBreakdown:
    """执行中观产业多维打分、周期属性自适应与一票否决门禁。"""
    ind_type = resolve_industry_type(industry_name)
    mom_score = calculate_momentum_score(technicals)
    val_score = calculate_valuation_score(valuation, industry_type=ind_type)
    fund_score = calculate_fundamental_score(financials)
    crowd_penalty = calculate_crowding_penalty(
        constituents,
        turnover_p5y=turnover_p5y,
        overheat_threshold=veto_rules.overheat_turnover_percentile,
        momentum_score=mom_score,
    )

    # 加权综合得分
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
        if (
            np_yoy < veto_rules.profit_decay_threshold
            and rev_yoy < veto_rules.revenue_decay_threshold
        ):
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
        industry_type=ind_type,
        momentum_score=mom_score,
        valuation_score=val_score,
        fundamental_score=fund_score,
        crowding_penalty=crowd_penalty,
        composite_score=composite,
        quadrant=quadrant,
        veto_triggered=veto_triggered,
        veto_reasons=veto_reasons,
    )
