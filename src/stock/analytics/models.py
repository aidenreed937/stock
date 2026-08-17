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


class MomentumSpreadResult(BaseModel):
    """行业动量剪刀差分析结果。"""

    trade_date: date = Field(..., description="计算日期")
    top_leaders_120d: list[dict[str, Any]] = Field(
        default_factory=list, description="120日领跑行业 (前5)"
    )
    bottom_laggards_20d: list[dict[str, Any]] = Field(
        default_factory=list, description="20日超跌行业 (后5)"
    )
    spread: float = Field(..., description="动量剪刀差 (领跑行业均值 - 超跌行业均值 %)")
    is_switch_imminent: bool = Field(
        default=False, description="是否处于高低切换临界点 (剪刀差 > 35%)"
    )
    diagnostics: str = Field(default="", description="动量轮动诊断说明")


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


class MacroSignalItem(BaseModel):
    """宏观关键信号条目。"""

    category: str = Field(..., description="信号类型 (如 真实估值、宏观规模水位、短线情绪)")
    name: str = Field(..., description="信号名称 (如 股债比 EY/BY)")
    value_str: str = Field(..., description="格式化关键数字 (如 2.67x)")
    percentile_str: str = Field(..., description="10年分位文字 (如 86% 或 —)")
    status: str = Field(..., description="定性状态 (如 🟢 高 / 🟡 中枢偏上 / 🔴 过热)")
    description: str = Field(..., description="业务定性说明")


class MicroHealthSummary(BaseModel):
    """微观市场健康度领域模型。"""

    margin_ratio: float = Field(..., description="两融渗透率 (%)")
    margin_status: str = Field(..., description="两融定性 (如 温和健康)")
    pb_break_ratio: float = Field(..., description="破净率 (%)")
    pb_break_status: str = Field(..., description="破净定性 (如 大面积折价)")
    turnover_ratio: float = Field(..., description="换手率 (%)")
    turnover_status: str = Field(..., description="换手定性 (如 情绪适中)")
    above_ma60_ratio: float = Field(..., description="站上 MA60 比例 (%)")
    ma60_status: str = Field(..., description="中期趋势定性 (如 修复中)")


class DailyMarketScanSummary(BaseModel):
    """全市场每日量化体检领域聚合根 (全量计算指标、研判结论与行动清单)。"""

    trade_date: date = Field(..., description="体检基准交易日")
    one_sentence_summary: str = Field(..., description="一句话核心决策结论")
    signals: list[MacroSignalItem] = Field(default_factory=list, description="四个关键信号清单")
    undervalued_industries: list[str] = Field(
        default_factory=list, description="低估高性价比行业名称"
    )
    crowded_industries: list[str] = Field(default_factory=list, description="极端拥挤行业名称")
    top1_industry: str = Field(default="", description="成交最高行业名称")
    top1_tcr: float = Field(default=0.0, description="成交最高行业占比 (%)")
    micro_health: MicroHealthSummary = Field(..., description="微观健康度状态")
    action_items: list[str] = Field(default_factory=list, description="操作备忘清单")
    macro: MacroRegimeResult | None = Field(default=None, description="宏观周期状态机结果")
    tcr: TCRAnalysisResult | None = Field(default=None, description="中观行业拥挤度结果")
    pbroe: IndustryPBROEResult | None = Field(default=None, description="行业 PB-ROE 残差结果")
    momentum: MomentumSpreadResult | None = Field(default=None, description="行业动量剪刀差结果")
    margin: MarginPenetrationResult | None = Field(default=None, description="两融杠杆结果")
    breadth: MarketBreadthResult | None = Field(default=None, description="市场宽度结果")
    sentiment: MarketSentimentResult | None = Field(default=None, description="微观情绪结果")


class ScanEvaluatorConfig(BaseModel):
    """全市场量化扫描研判阈值与参数配置。"""

    # 宏观分位带阈值
    eyby_high_pctl: float = Field(default=70.0, description="股债比高性价比分位阈值")
    eyby_low_pctl: float = Field(default=30.0, description="股债比低性价比防御阈值")
    pb_extreme_high_pctl: float = Field(default=75.0, description="全 A PB 极高分位阈值")
    pb_high_pctl: float = Field(default=60.0, description="全 A PB 偏高分位阈值")
    pb_mid_high_pctl: float = Field(default=55.0, description="全 A PB 中枢偏上阈值")
    pb_reasonable_pctl: float = Field(default=30.0, description="全 A PB 中枢合理下限阈值")
    buffett_extreme_pctl: float = Field(default=90.0, description="巴菲特指标极高警示阈值")
    buffett_high_pctl: float = Field(default=85.0, description="巴菲特指标偏高分位阈值")
    buffett_mid_high_pctl: float = Field(default=70.0, description="巴菲特指标中偏高阈值")
    buffett_reasonable_pctl: float = Field(default=30.0, description="巴菲特指标中枢合理下限阈值")

    # 短线宽度信号阈值
    above_ma20_hot: float = Field(default=80.0, description="站上 MA20 短线过热阈值")
    above_ma20_healthy: float = Field(default=40.0, description="站上 MA20 短线健康阈值")

    # 微观健康度区间阈值
    margin_healthy_min: float = Field(default=2.2, description="两融渗透率健康区间下限")
    margin_healthy_max: float = Field(default=2.8, description="两融渗透率健康区间上限")
    pb_break_warning: float = Field(default=7.0, description="破净率大面积折价警戒线")
    pb_break_moderate: float = Field(default=4.0, description="破净率部分折价线")
    turnover_hot: float = Field(default=6.0, description="换手率交易火热阈值")
    turnover_moderate: float = Field(default=3.0, description="换手率情绪适中阈值")
    above_ma60_bull: float = Field(default=60.0, description="站上 MA60 多头走强阈值")
    above_ma60_repair: float = Field(default=30.0, description="站上 MA60 修复中阈值")

    # 行动清单配置
    default_equity_exposure: float = Field(default=0.70, description="缺失宏观信号时的默认仓位暴露")
    exposure_min_bound: int = Field(default=20, description="仓位下限")
    exposure_max_bound: int = Field(default=95, description="仓位上限")
    exposure_buffer_pct: int = Field(default=10, description="仓位浮动缓冲区间")
