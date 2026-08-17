"""量化因子工程与特征库调度包。

因子底层原子算子已下沉至 `stock.analytics.primitives`，本模块保留 FactorEngine 及向后兼容导出。
"""

from __future__ import annotations

from stock.analytics.factors.engine import FactorEngine
from stock.analytics.primitives import (
    calculate_amihud_illiquidity,
    calculate_atr,
    calculate_bollinger_bandwidth,
    calculate_distance_to_high,
    calculate_ema_spread,
    calculate_equity_risk_premium,
    calculate_main_moneyflow_factors,
    calculate_margin_factors,
    calculate_momentum,
    calculate_realized_volatility,
    calculate_rolling_percentile,
    calculate_short_term_reversal,
    calculate_turnover_factors,
    calculate_volume_surprise,
    calculate_yield_curve_slope,
)

__all__ = [
    "FactorEngine",
    "calculate_amihud_illiquidity",
    "calculate_atr",
    "calculate_bollinger_bandwidth",
    "calculate_distance_to_high",
    "calculate_ema_spread",
    "calculate_equity_risk_premium",
    "calculate_main_moneyflow_factors",
    "calculate_margin_factors",
    "calculate_momentum",
    "calculate_realized_volatility",
    "calculate_rolling_percentile",
    "calculate_short_term_reversal",
    "calculate_turnover_factors",
    "calculate_volume_surprise",
    "calculate_yield_curve_slope",
]
