"""内置策略池。"""

from stock_strategy.base import BaseStrategy
from stock_strategy.pool.double_sma_rsi import DoubleSmaRsiStrategy
from stock_strategy.pool.macd_cross import MACDCrossStrategy
from stock_strategy.pool.macro_risk_v3 import MacroRiskV3Strategy
from stock_strategy.pool.macro_rotation_v4 import MacroRotationV4Strategy
from stock_strategy.pool.macro_rotation_v5 import MacroRotationV5Strategy
from stock_strategy.pool.macro_rotation_v6 import MacroRotationV6Strategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "DoubleSmaRsiStrategy": DoubleSmaRsiStrategy,
    "MACDCrossStrategy": MACDCrossStrategy,
    "MacroRiskV3Strategy": MacroRiskV3Strategy,
    "MacroRotationV4Strategy": MacroRotationV4Strategy,
    "MacroRotationV5Strategy": MacroRotationV5Strategy,
    "MacroRotationV6Strategy": MacroRotationV6Strategy,
}


def create_strategy(cls_name: str, **kwargs: object) -> BaseStrategy:
    """按类名动态创建策略实例。"""
    cls = STRATEGY_REGISTRY.get(cls_name)
    if cls is None:
        raise ValueError(f"未知策略类: {cls_name} (已注册: {list(STRATEGY_REGISTRY.keys())})")
    return cls(**kwargs)  # type: ignore[arg-type]


__all__ = [
    "STRATEGY_REGISTRY",
    "DoubleSmaRsiStrategy",
    "MACDCrossStrategy",
    "MacroRiskV3Strategy",
    "MacroRotationV4Strategy",
    "MacroRotationV5Strategy",
    "MacroRotationV6Strategy",
    "create_strategy",
]
