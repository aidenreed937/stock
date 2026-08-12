"""研究阶段策略运行与风险约束。"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl

from stock.models.config import StrategyConfig
from stock.strategy.pool.double_sma_rsi import DoubleSmaRsiStrategy
from stock.strategy.signal import Signal


@dataclass(frozen=True)
class SignalReport:
    """一次研究运行的可审计信号输出。"""

    strategy_name: str
    strategy_version: str
    generated_at: datetime
    data_source: str
    symbols: tuple[str, ...]
    signals: tuple[Signal, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的研究报告字典。"""
        return {
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "generated_at": self.generated_at.isoformat(),
            "data_source": self.data_source,
            "symbols": list(self.symbols),
            "signals": [
                {
                    "symbol": signal.symbol,
                    "direction": signal.direction.name,
                    "target_weight": signal.target_weight,
                    "reason": signal.reason,
                    "timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
                }
                for signal in self.signals
            ],
        }


class StrategyRunner:
    """按标的分组执行研究策略，不执行订单或成交。"""

    def __init__(self, config: StrategyConfig, data_source: str) -> None:
        """初始化策略运行器。"""
        self.config = config
        self.data_source = data_source

    def run(self, data: pl.DataFrame) -> SignalReport:
        """按标的执行策略并返回结构化信号报告。"""
        strategy = DoubleSmaRsiStrategy(self.config)
        signals: list[Signal] = []
        for symbol, group in (
            data.sort(["symbol", "trade_date"]).partition_by("symbol", as_dict=True).items()
        ):
            symbol_value = symbol[0] if isinstance(symbol, tuple) else symbol
            signals.extend(
                strategy.on_bar(group.with_columns(pl.lit(symbol_value).alias("symbol")))
            )
        return SignalReport(
            strategy_name=self.config.name,
            strategy_version=self.config.version,
            generated_at=datetime.now(),
            data_source=self.data_source,
            symbols=tuple(self.config.universe.symbols),
            signals=tuple(signals),
        )
