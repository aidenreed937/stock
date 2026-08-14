"""宏观四象限状态机分析器 (Macro Regime Switch Engine)。

综合结合：
    1. 真实估值 (相对债券): 沪深 300 无量纲股债收益比 (EY/BY)；
    2. 真实估值 (全 A 资产): 中证全指 (000985) 等权 PB 及 10 年历史分位；
    3. 宏观规模水位 (宏观温度计): 全市场证券化率 (Buffett Ratio, 市值/GDP)。

严谨输出大级别宏观周期定性与建议权益仓位。
"""

from __future__ import annotations

from datetime import date

from stock.analytics.macro.all_market import AllMarketValuationAnalyzer
from stock.analytics.macro.buffett import BuffettIndicatorCalculator
from stock.analytics.macro.ey_by import EYBYCalculator
from stock.analytics.models import (
    AllMarketValuationResult,
    BuffettRatioResult,
    EYBYRatioResult,
    MacroRegime,
    MacroRegimeResult,
)


def _check_opportunity_zone(
    eyby: EYBYRatioResult | None,
    all_market: AllMarketValuationResult | None,
    buffett: BuffettRatioResult | None,
) -> tuple[MacroRegime, str, float, list[str]] | None:
    """检查是否处于大级别战略机会区。"""
    if not (eyby and eyby.is_strategic_bottom):
        return None
    drivers = [f"股债收益比达到 {eyby.ey_by_ratio:.2f}x (>=2.2x 战略级利差高性价比)"]

    if all_market:
        drivers.append(
            f"全 A 资产水位处于 {all_market.pb_percentile_10y:.1f}% 分位 "
            f"({all_market.index_name} PB {all_market.pb_ew:.2f})"
        )

    # 股债极高性价比 + 证券化率低 + 全 A 低估 = 绝对历史黄金底
    is_gold_buf = bool(buffett and buffett.is_golden_bottom)
    is_low_all = not all_market or all_market.pb_percentile_10y < 30.0
    if is_gold_buf and is_low_all:
        if buffett:
            drivers.append(f"证券化率低至 {buffett.securitization_ratio:.1f}% (<65% 黄金带)")
        desc = "战略级大底黄金机会区 (多维指标深度共振大底，建议维持极高权益仓位)"
        return MacroRegime.OPPORTUNITY_ZONE, desc, 0.95, drivers

    # 股债比高，但证券化率高/全 A 水位处于中枢偏高 = 结构性机会区
    is_high_buf = bool(buffett and buffett.securitization_ratio > 80.0)
    is_high_all = bool(all_market and all_market.pb_percentile_10y > 60.0)
    if is_high_buf or is_high_all:
        drivers.append(
            "【结构分化提示】全 A 水位与证券化率偏高，性价比主要受超低国债利率推升，"
            "属结构性行情，建议精选低估高股息资产"
        )
        desc = "结构性战略机会区 (大盘股债利差极具性价比，全 A 水位中枢偏上，建议优选低估洼地)"
        return MacroRegime.OPPORTUNITY_ZONE, desc, 0.75, drivers

    desc = "战略机会区 (大盘股债性价比极高，建议积极提升权益仓位)"
    return MacroRegime.OPPORTUNITY_ZONE, desc, 0.85, drivers


def _check_bubble_risk(
    eyby: EYBYRatioResult | None,
    all_market: AllMarketValuationResult | None,
    buffett: BuffettRatioResult | None,
) -> tuple[MacroRegime, str, float, list[str]] | None:
    """检查是否处于周期大顶泡沫警戒区。"""
    if not (eyby and eyby.is_bubble_peak):
        return None
    drivers = [f"股债收益比严重压缩至 {eyby.ey_by_ratio:.2f}x (<1.15x 大牛顶警戒)"]
    desc = "宏观周期大顶泡沫区 (股债收益率严重倒挂，强制战略避险与大幅减仓)"
    exposure = 0.15
    if buffett and buffett.is_bubble_overheat:
        drivers.append(f"证券化率突破 {buffett.securitization_ratio:.1f}% (>86% 极端过热区)")
        exposure = 0.05
    return MacroRegime.BUBBLE_RISK, desc, exposure, drivers


def _determine_regime(
    eyby: EYBYRatioResult | None,
    all_market: AllMarketValuationResult | None,
    buffett: BuffettRatioResult | None,
) -> tuple[MacroRegime, str, float, list[str]]:
    """综合评估宏观象限与建议仓位。"""
    opp = _check_opportunity_zone(eyby, all_market, buffett)
    if opp is not None:
        return opp

    bubble = _check_bubble_risk(eyby, all_market, buffett)
    if bubble is not None:
        return bubble

    drivers: list[str] = []
    is_def_eyby = bool(eyby and eyby.ey_by_ratio < 1.3)
    is_def_buff = bool(buffett and buffett.securitization_ratio > 80.0)
    is_def_all = bool(all_market and all_market.pb_percentile_10y > 75.0)

    if is_def_eyby or is_def_buff or is_def_all:
        if is_def_eyby and eyby:
            drivers.append(f"股债收益比偏低 ({eyby.ey_by_ratio:.2f}x < 1.3x)")
        if is_def_all and all_market:
            drivers.append(f"全 A 水位偏高 ({all_market.pb_percentile_10y:.1f}% 分位)")
        if is_def_buff and buffett:
            drivers.append(f"证券化率偏高 ({buffett.securitization_ratio:.1f}% > 80%)")
        desc = "宏观中性防御区 (估值性价比有所压缩，适度控制权益敞口)"
        return MacroRegime.DEFENSIVE, desc, 0.45, drivers

    if eyby:
        drivers.append(f"股债收益比处于合理中枢 ({eyby.ey_by_ratio:.2f}x)")
    if all_market:
        drivers.append(f"全 A 资产水位处于合理区间 ({all_market.pb_percentile_10y:.1f}% 分位)")
    if buffett:
        drivers.append(f"证券化率处于合理区间 ({buffett.securitization_ratio:.1f}%)")
    desc = "常态合理轮动区 (宏观估值适中，主打行业轮动与多因子阿尔法)"
    return MacroRegime.NORMAL_ROTATION, desc, 0.70, drivers


class MacroRegimeAnalyzer:
    """宏观四象限周期状态机。"""

    def __init__(
        self,
        eyby_calc: EYBYCalculator | None = None,
        buffett_calc: BuffettIndicatorCalculator | None = None,
        all_market_analyzer: AllMarketValuationAnalyzer | None = None,
    ) -> None:
        """初始化状态机。"""
        self.eyby_calc = eyby_calc or EYBYCalculator()
        self.buffett_calc = buffett_calc or BuffettIndicatorCalculator()
        self.all_market_analyzer = all_market_analyzer or AllMarketValuationAnalyzer()

    def evaluate_regime(
        self,
        target_date: date | None = None,
        index_symbol: str = "000300",
    ) -> MacroRegimeResult | None:
        """评估指定交易日的宏观周期状态与建议仓位。"""
        eyby_res = self.eyby_calc.calculate_latest(symbol=index_symbol, target_date=target_date)
        all_m_res = self.all_market_analyzer.calculate_latest(
            symbol="000985", target_date=target_date
        )
        buffett_res = self.buffett_calc.calculate_latest(target_date=target_date)

        if eyby_res is None and buffett_res is None and all_m_res is None:
            return None

        eval_date = (
            eyby_res.trade_date
            if eyby_res
            else (
                all_m_res.trade_date
                if all_m_res
                else (buffett_res.trade_date if buffett_res else date.today())
            )
        )

        regime, desc, exposure, drivers = _determine_regime(eyby_res, all_m_res, buffett_res)

        return MacroRegimeResult(
            trade_date=eval_date,
            regime=regime,
            regime_desc=desc,
            suggested_equity_exposure=exposure,
            ey_by=eyby_res,
            all_market=all_m_res,
            buffett=buffett_res,
            key_drivers=drivers,
        )
