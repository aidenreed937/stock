"""基础量化与估值原子算子 (Primitives)。

包含纯函数、无状态技术指标、多因子特征算子与估值分位数计算工具。
本包下所有算子均满足：零内部业务依赖，仅依赖 Polars/标准库，输入输出均为纯数据结构。
"""

from __future__ import annotations

from stock_analytics.primitives.cross_sectional import (
    cross_sectional_ols,
    cross_sectional_zscore,
    mad_winsorize,
    quantile_bucket,
)
from stock_analytics.primitives.factor_evaluation import (
    add_forward_returns,
    cumulative_ic,
    ic_decay,
    ic_summary,
    rank_ic_series,
)
from stock_analytics.primitives.factor_quantile import (
    quantile_forward_returns,
    quantile_summary,
)
from stock_analytics.primitives.indicators import (
    DEFAULT_EMA_WINDOW,
    DEFAULT_MACD_FAST,
    DEFAULT_MACD_SIGNAL,
    DEFAULT_MACD_SLOW,
    DEFAULT_RSI_WINDOW,
    DEFAULT_SMA_WINDOW,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
)
from stock_analytics.primitives.liquidity import (
    calculate_amihud_illiquidity,
    calculate_turnover_factors,
    calculate_volume_surprise,
)
from stock_analytics.primitives.macro import (
    calculate_macro_spread,
    calculate_securitization_ratio,
    calculate_yield_curve_slope,
)
from stock_analytics.primitives.momentum import (
    calculate_distance_to_high,
    calculate_ema_spread,
    calculate_momentum,
    calculate_short_term_reversal,
)
from stock_analytics.primitives.moneyflow import (
    calculate_main_moneyflow_factors,
    calculate_margin_factors,
)
from stock_analytics.primitives.neutralization import (
    cross_sectional_neutralize,
    cross_sectional_orthogonalize,
)
from stock_analytics.primitives.rotation import (
    calculate_momentum_acceleration,
    calculate_rps,
    calculate_weighted_momentum,
)
from stock_analytics.primitives.valuation import (
    calculate_dividend_spread,
    calculate_equity_risk_premium,
    calculate_ey_by_ratio,
    calculate_rolling_percentile,
)
from stock_analytics.primitives.volatility import (
    calculate_atr,
    calculate_bollinger_bandwidth,
    calculate_garman_klass_volatility,
    calculate_parkinson_volatility,
    calculate_realized_volatility,
    calculate_shadow_ratio,
)

__all__ = [
    "DEFAULT_EMA_WINDOW",
    "DEFAULT_MACD_FAST",
    "DEFAULT_MACD_SIGNAL",
    "DEFAULT_MACD_SLOW",
    "DEFAULT_RSI_WINDOW",
    "DEFAULT_SMA_WINDOW",
    "add_forward_returns",
    "calculate_amihud_illiquidity",
    "calculate_atr",
    "calculate_bollinger_bandwidth",
    "calculate_distance_to_high",
    "calculate_dividend_spread",
    "calculate_ema",
    "calculate_ema_spread",
    "calculate_equity_risk_premium",
    "calculate_ey_by_ratio",
    "calculate_garman_klass_volatility",
    "calculate_macd",
    "calculate_macro_spread",
    "calculate_main_moneyflow_factors",
    "calculate_margin_factors",
    "calculate_momentum",
    "calculate_momentum_acceleration",
    "calculate_parkinson_volatility",
    "calculate_realized_volatility",
    "calculate_rolling_percentile",
    "calculate_rps",
    "calculate_rsi",
    "calculate_securitization_ratio",
    "calculate_shadow_ratio",
    "calculate_short_term_reversal",
    "calculate_sma",
    "calculate_turnover_factors",
    "calculate_volume_surprise",
    "calculate_weighted_momentum",
    "calculate_yield_curve_slope",
    "cross_sectional_neutralize",
    "cross_sectional_ols",
    "cross_sectional_orthogonalize",
    "cross_sectional_zscore",
    "cumulative_ic",
    "ic_decay",
    "ic_summary",
    "mad_winsorize",
    "quantile_bucket",
    "quantile_forward_returns",
    "quantile_summary",
    "rank_ic_series",
]
