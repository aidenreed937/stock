"""量化分析指标与状态机的强类型数据模型。"""

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MacroRegime(StrEnum):
    """宏观四象限大级别周期状态。"""

    OPPORTUNITY_ZONE = "OPPORTUNITY_ZONE"  # 战略级大底黄金机会区 (高胜率高赔率)
    NORMAL_ROTATION = "NORMAL_ROTATION"  # 常态合理轮动区 (阿尔法选股与中观轮动)
    BUBBLE_RISK = "BUBBLE_RISK"  # 宏观周期大顶泡沫区 (收益率倒挂，强制防御减仓)
    DEFENSIVE = "DEFENSIVE"  # 宏观中性防御区 (估值偏高或杠杆偏高，适度防守)


class ValuationZone(StrEnum):
    """估值与定价区间标尺。"""

    EXTREME_LOW = "EXTREME_LOW"  # 极度低估 / 深度折价
    LOW = "LOW"  # 偏低估
    FAIR = "FAIR"  # 合理中枢
    HIGH = "HIGH"  # 偏高估
    EXTREME_HIGH = "EXTREME_HIGH"  # 极度高估 / 泡沫过热


class EYBYRatioResult(BaseModel):
    """股债收益比 (Earnings Yield / Bond Yield Ratio, EY/BY) 计算结果。"""

    trade_date: date = Field(..., description="计算日期")
    symbol: str = Field(..., description="指数标的代码")
    pe_ttm: float = Field(..., description="指数市盈率 TTM")
    earnings_yield: float = Field(..., description="股票盈利收益率 (1 / PE_TTM * 100%)")
    bond_yield_10y: float = Field(..., description="10年期中债国债到期收益率 (%)")
    ey_by_ratio: float = Field(..., description="无量纲股债收益比 (EY / BY)")
    percentile_10y: float = Field(..., description="过去 10 年历史分位数 (0~100%)")
    zone: ValuationZone = Field(..., description="估值区间判定")
    zone_desc: str = Field(..., description="中文描述说明")
    is_strategic_bottom: bool = Field(default=False, description="是否处于战略级大熊底 (>2.2x)")
    is_bubble_peak: bool = Field(default=False, description="是否处于大牛顶警戒区 (<1.15x)")


class BuffettRatioResult(BaseModel):
    """证券化率 (巴菲特指标总市值 / GDP TTM) 计算结果。"""

    trade_date: date = Field(..., description="计算日期")
    total_market_cap_yi: float = Field(..., description="全市场总市值 (亿元)")
    gdp_ttm_yi: float = Field(..., description="滚动 4 季度 GDP TTM (亿元)")
    securitization_ratio: float = Field(..., description="证券化率 (%)")
    percentile_10y: float = Field(..., description="过去 10 年历史分位数 (0~100%)")
    zone: ValuationZone = Field(..., description="证券化率区间判定")
    zone_desc: str = Field(..., description="中文描述说明")
    is_golden_bottom: bool = Field(default=False, description="是否处于历史黄金建仓带 (<65%)")
    is_bubble_overheat: bool = Field(default=False, description="是否处于极端泡沫过热区 (>86%)")


class MacroRegimeResult(BaseModel):
    """宏观四象限状态机综合判定结果。"""

    trade_date: date = Field(..., description="计算日期")
    regime: MacroRegime = Field(..., description="宏观周期状态")
    regime_desc: str = Field(..., description="状态中文描述")
    suggested_equity_exposure: float = Field(..., description="建议权益仓位暴露上限 (0.0 ~ 1.0)")
    ey_by: EYBYRatioResult | None = Field(default=None, description="股债收益比详情")
    buffett: BuffettRatioResult | None = Field(default=None, description="证券化率详情")
    key_drivers: list[str] = Field(default_factory=list, description="状态驱动主因")


class SingleIndustryTCR(BaseModel):
    """单行业成交额拥挤度详情。"""

    industry_code: str = Field(..., description="申万行业代码")
    industry_name: str = Field(..., description="行业名称")
    amount_yi: float = Field(..., description="当日成交金额 (亿元)")
    tcr: float = Field(..., description="成交额拥挤度占比 (%)")
    is_crowded: bool = Field(default=False, description="是否达到极端拥挤度警戒 (>20%)")
    crowding_penalty: float = Field(default=0.0, description="拥挤度惩罚因子 (0.0 ~ 1.0)")


class TCRAnalysisResult(BaseModel):
    """中观全行业成交额拥挤度 (TCR) 日度分析结果。"""

    trade_date: date = Field(..., description="计算日期")
    total_amount_yi: float = Field(..., description="31 行业总成交额 (亿元)")
    industries: list[SingleIndustryTCR] = Field(
        default_factory=list, description="行业明细 (按 TCR 降序)"
    )
    crowded_industries: list[str] = Field(default_factory=list, description="极端拥挤行业名称列表")
    top1_industry: str = Field(default="", description="成交占比最高行业")
    top1_tcr: float = Field(default=0.0, description="最高行业成交占比 (%)")


class IndustryPBROEResult(BaseModel):
    """行业 PB-ROE 残差分析与性价比排序结果。"""

    trade_date: date = Field(..., description="计算日期")
    regression_alpha: float = Field(..., description="回归截距")
    regression_beta: float = Field(..., description="回归斜率")
    r_squared: float = Field(..., description="回归拟合优度 R^2")
    industries: list[dict[str, Any]] = Field(
        default_factory=list, description="包含 code, name, pb, roe, residual, is_undervalued"
    )
    undervalued_industries: list[str] = Field(
        default_factory=list, description="低估高性价比行业 (低 PB、高 ROE 残差)"
    )


class MarginPenetrationResult(BaseModel):
    """两融杠杆渗透率分析结果。"""

    trade_date: date = Field(..., description="计算日期")
    margin_balance_yi: float = Field(..., description="全市场两融总余额 (亿元)")
    circ_mv_yi: float = Field(..., description="全市场流通总市值 (亿元)")
    margin_penetration: float = Field(..., description="两融渗透率 (%)")
    is_cleared_bottom: bool = Field(default=False, description="是否处于杠杆彻底出清底 (<2.2%)")
    is_overloaded_peak: bool = Field(default=False, description="是否处于杠杆过载脆弱区 (>3.5%)")
    zone_desc: str = Field(..., description="状态中文描述")


class MarketBreadthResult(BaseModel):
    """多周期市场宽度与背离诊断结果。"""

    trade_date: date = Field(..., description="计算日期")
    total_stocks: int = Field(..., description="有效统计股票数")
    above_ma20_ratio: float = Field(..., description="站上 MA20 短线比例 (%)")
    above_ma60_ratio: float = Field(..., description="站上 MA60 中期比例 (%)")
    above_ma120_ratio: float = Field(..., description="站上 MA120 半年线比例 (%)")
    is_bottom_divergence: bool = Field(default=False, description="是否出现宽度底背离")
    is_top_divergence: bool = Field(default=False, description="是否出现宽度顶背离")
    diagnostics: list[str] = Field(default_factory=list, description="背离与状态诊断文本")


class MarketSentimentResult(BaseModel):
    """市场微观情绪与极值特征。"""

    trade_date: date = Field(..., description="计算日期")
    pb_break_ratio: float = Field(..., description="全市场破净率 PB<1.0 比例 (%)")
    turnover_ratio: float = Field(..., description="全市场换手率 (%)")
    is_shrink_volume_bottom: bool = Field(default=False, description="是否出现地量见地价 (<2.3%)")
    is_huge_volume_peak: bool = Field(default=False, description="是否出现天量见天价 (>5.5%)")
    is_wide_pb_broken_bottom: bool = Field(
        default=False, description="是否处于大面积资产折价破净底 (>10%)"
    )
    diagnostics: list[str] = Field(default_factory=list, description="微观情绪特征描述")
