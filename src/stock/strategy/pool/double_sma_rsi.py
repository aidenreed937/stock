"""双均线与 RSI 过滤策略。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl  # noqa: TC002

from stock.analytics.indicators import calculate_rsi, calculate_sma
from stock.models.config import StrategyConfig  # noqa: TC001
from stock.strategy.base import BaseStrategy
from stock.strategy.context import Context  # noqa: TC001
from stock.strategy.signal import Signal, SignalDirection

if TYPE_CHECKING:
    from datetime import date, datetime


class DoubleSmaRsiStrategy(BaseStrategy):
    """快慢均线交叉，并使用 RSI 阈值过滤信号。"""

    def __init__(self, config: StrategyConfig, context: Context | None = None) -> None:
        """初始化策略及其研究配置。"""
        super().__init__(context)
        self.config = config

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理单个标的完整历史窗口并生成当前最后一日信号。"""
        sma = self.config.indicators.sma
        rsi_config = self.config.indicators.rsi
        minimum_rows = max(sma.slow_period, rsi_config.period) + 1
        if len(data) < minimum_rows or not {"symbol", "trade_date", "close"}.issubset(data.columns):
            return []
        df = data.sort("trade_date")
        df = calculate_sma(df, window=sma.fast_period)
        df = calculate_sma(df, window=sma.slow_period)
        df = calculate_rsi(df, window=rsi_config.period)
        fast = df[f"sma_{sma.fast_period}"]
        slow = df[f"sma_{sma.slow_period}"]
        rsi = df[f"rsi_{rsi_config.period}"]
        if any(value is None for value in (fast[-1], fast[-2], slow[-1], slow[-2], rsi[-1])):
            return []
        symbol = str(df["symbol"][-1])
        raw_timestamp = df["trade_date"][-1]
        timestamp: date | datetime = raw_timestamp
        if fast[-2] <= slow[-2] and fast[-1] > slow[-1] and rsi[-1] <= rsi_config.overbought:
            return [
                Signal(
                    symbol,
                    SignalDirection.BUY,
                    self.config.risk_management.max_position_per_symbol,
                    "SMA_GOLDEN_CROSS_RSI_FILTER",
                    timestamp,
                )
            ]
        if fast[-2] >= slow[-2] and fast[-1] < slow[-1] and rsi[-1] >= rsi_config.oversold:
            return [
                Signal(symbol, SignalDirection.SELL, 0.0, "SMA_DEAD_CROSS_RSI_FILTER", timestamp)
            ]
        return []
