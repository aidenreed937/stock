"""内置策略池。"""

from stock_strategy.pool.double_sma_rsi import DoubleSmaRsiStrategy
from stock_strategy.pool.macd_cross import MACDCrossStrategy

__all__ = ["DoubleSmaRsiStrategy", "MACDCrossStrategy"]
