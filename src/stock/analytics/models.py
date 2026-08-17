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


class AllMarketValuationResult(BaseModel):
    """全 A 股市场整体资产水位 (以中证全指 000985 等权 PB 为核心标尺) 计算结果。"""

    trade_date: date = Field(..., description="计算日期")
    symbol: str = Field(default="000985", description="指数代码 (默认中证全指)")
    index_name: str = Field(default="中证全指", description="指数中文名称")
    pb_ew: float = Field(..., description="等权市净率 PB (剔除微利小票盈利分母扭曲)")
    pb_percentile_10y: float = Field(..., description="过去 10 年 PB 历史分位数 (0~100%)")
    pe_ttm_ew: float = Field(..., description="等权市盈率 PE-TTM")
    pe_percentile_10y: float = Field(..., description="过去 10 年 PE 历史分位数 (0~100%)")
    zone: ValuationZone = Field(..., description="全 A 水位区间判定")
    zone_desc: str = Field(..., description="中文描述说明")


class MacroRegimeResult(BaseModel):
    """宏观四象限状态机综合判定结果。"""

    trade_date: date = Field(..., description="计算日期")
    regime: MacroRegime = Field(..., description="宏观周期状态")
    regime_desc: str = Field(..., description="状态中文描述")
    suggested_equity_exposure: float = Field(..., description="建议权益仓位暴露上限 (0.0 ~ 1.0)")
    ey_by: EYBYRatioResult | None = Field(default=None, description="股债收益比详情")
    all_market: AllMarketValuationResult | None = Field(
        default=None, description="全 A 资产水位详情"
    )
    buffett: BuffettRatioResult | None = Field(default=None, description="证券化率详情")
    key_drivers: list[str] = Field(default_factory=list, description="状态驱动主因")


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
