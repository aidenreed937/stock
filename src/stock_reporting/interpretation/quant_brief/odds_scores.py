"""胜率/赔率环境分项计算（cross_cycle 拆分模块，避免类规模超限）。"""

from __future__ import annotations

from stock_reporting.interpretation.quant_brief.config import CrossCycleConfig

_EXTREME = "extreme"
_SYNCHRONIZED = "synchronized"
_DIVERGENT = "divergent"


def calculate_win_parts(
    matrix: CrossCycleConfig,
    div_level: str,
    fast: float | None,
    short_5d: float | None,
    width_value: float | None,
    fund_value: float | None,
    transmission: str,
) -> tuple[dict[str, float], float]:
    """计算胜率环境分项与原始分。"""
    parts: dict[str, float] = {}

    if div_level == _SYNCHRONIZED:
        parts["背离同步"] = matrix.win_sync_bonus
    elif div_level == _EXTREME:
        if fast is not None and fast <= matrix.short_ice_threshold:
            parts["冰极背离"] = matrix.win_ice_extreme_penalty
        elif fast is not None and fast >= matrix.short_hot_threshold:
            parts["热极背离"] = matrix.win_hot_extreme_penalty
        else:
            parts["极背离"] = 0.0
    elif div_level == _DIVERGENT:
        parts["背离发散"] = 0.0

    if short_5d is not None:
        if short_5d < matrix.short_ice_threshold:
            parts["短线冰点"] = matrix.win_short_ice_bonus
        elif short_5d > matrix.short_hot_threshold:
            parts["短线过热"] = matrix.win_short_hot_penalty
        else:
            parts["短线中性"] = 0.0

    if width_value is not None:
        if width_value >= matrix.width_healthy_threshold:
            parts["宽度健康"] = matrix.win_width_healthy_bonus
        elif width_value < matrix.width_weak_threshold:
            parts["宽度偏弱"] = matrix.win_width_weak_penalty
        else:
            parts["宽度中性"] = 0.0

    if fund_value is not None:
        parts["主力20日净流入"] = (
            matrix.win_fund_confirmed_bonus if fund_value >= 0 else matrix.win_fund_outflow_penalty
        )

    if transmission and ("pending" in transmission or "shock" in transmission):
        parts["外盘待确认"] = matrix.win_external_pending_penalty

    return parts, float(sum(parts.values()))


def calculate_odds_parts(
    matrix: CrossCycleConfig,
    slow: float | None,
    valuation: float | None,
    diffusion_60d: float | None,
    crowded_share: float | None,
    macro_liquidity: float | None,
    background_pressure: float | None,
) -> tuple[dict[str, float], float]:
    """计算赔率环境分项与原始分。"""
    parts: dict[str, float] = {}

    if slow is not None:
        if slow < matrix.slow_low_threshold:
            parts["慢温低位"] = matrix.odds_slow_low_bonus
        elif slow >= matrix.slow_high_threshold:
            parts["慢温高位"] = matrix.odds_slow_high_penalty
        else:
            parts["慢温中性"] = 0.0

    if valuation is not None:
        if valuation < matrix.valuation_low_threshold:
            parts["估值低位"] = matrix.odds_valuation_low_bonus
        elif valuation >= matrix.valuation_high_threshold:
            parts["估值高位"] = matrix.odds_valuation_high_penalty
        else:
            parts["估值中性"] = 0.0

    if diffusion_60d is not None:
        if diffusion_60d >= matrix.diffusion_high_threshold:
            parts["扩散高位"] = matrix.odds_diffusion_high_penalty
        elif diffusion_60d < matrix.diffusion_low_threshold:
            parts["扩散低位"] = matrix.odds_diffusion_low_bonus
        else:
            parts["扩散中性"] = 0.0

    if crowded_share is not None:
        if crowded_share == 0:
            parts["无拥挤行业"] = matrix.odds_crowding_none_bonus
        elif crowded_share > matrix.crowding_share_threshold:
            parts["拥挤行业偏高"] = matrix.odds_crowding_high_penalty
        else:
            parts["拥挤中性"] = 0.0

    if macro_liquidity is not None:
        if macro_liquidity >= matrix.macro_tight_threshold:
            parts["宏观偏紧"] = matrix.odds_macro_tight_penalty
        elif macro_liquidity < matrix.macro_loose_threshold:
            parts["宏观宽松"] = matrix.odds_macro_loose_bonus
        else:
            parts["宏观中性"] = 0.0

    if background_pressure is not None and background_pressure > matrix.external_pressure_threshold:
        parts["外盘高压"] = matrix.odds_external_pressure_penalty

    return parts, float(sum(parts.values()))


__all__ = ["calculate_odds_parts", "calculate_win_parts"]
