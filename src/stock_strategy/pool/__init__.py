"""内置策略池。"""

from stock_strategy.pool.double_sma_rsi import DoubleSmaRsiStrategy
from stock_strategy.pool.macd_cross import MACDCrossStrategy
from stock_strategy.pool.macro_risk_v3 import MacroRiskV3Strategy
from stock_strategy.pool.macro_rotation_v4 import MacroRotationV4Strategy

__all__ = [
    "DoubleSmaRsiStrategy",
    "MACDCrossStrategy",
    "MacroRiskV3Strategy",
    "MacroRotationV4Strategy",
]
