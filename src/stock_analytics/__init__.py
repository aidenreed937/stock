"""量化分析层 (Analytics Layer)。

结构说明:
    1. primitives: 纯无状态数学与技术指标算子 (SMA, EMA, MACD, RSI, EY/BY 等)；
    2. metrics: 领域计算引擎与时序指标萃取器 (MetricEngine)；
    3. features: 统一特征工程存储与跨维度特征表 (FeatureStore)；
    4. pipelines: L3 业务决策管线 (market_temperature, industry_structure, investor_brief)。
"""

from stock_analytics.models import (
    AllMarketValuationResult,
    BuffettRatioResult,
    EYBYRatioResult,
    IndustryPBROEResult,
    MacroRegime,
    MacroRegimeResult,
    ValuationZone,
)
from stock_analytics.primitives import (
    calculate_ema,
    calculate_equity_risk_premium,
    calculate_ey_by_ratio,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
)

__all__ = [
    "AllMarketValuationResult",
    "BuffettRatioResult",
    "EYBYRatioResult",
    "IndustryPBROEResult",
    "MacroRegime",
    "MacroRegimeResult",
    "ValuationZone",
    "calculate_ema",
    "calculate_equity_risk_premium",
    "calculate_ey_by_ratio",
    "calculate_macd",
    "calculate_rsi",
    "calculate_sma",
]
