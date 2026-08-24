"""MACD 双均线交叉策略示例。"""

import polars as pl

from stock_analytics.primitives import calculate_macd
from stock_strategy import BaseStrategy, Signal, SignalDirection
from stock_strategy.context import Context


class MACDCrossStrategy(BaseStrategy):
    """MACD 金叉买入、死叉卖出策略。"""

    def __init__(self, context: Context | None = None, target_weight: float = 0.2) -> None:
        """初始化 MACD 策略。

        Args:
            context: 策略上下文
            target_weight: 触发买入信号时的目标仓位占比 (默认 20%)
        """
        super().__init__(context)
        self.target_weight = target_weight

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理单个标的的 K 线数据切片，返回生成的信号。

        Args:
            data: 历史 K 线序列 (必须包含 close 和 symbol 字段，按时间正序排列)。
        """
        # 数据过少无法计算慢线 (26) + signal (9) 的 EMA
        if len(data) < 35:
            return []

        # 保证时间序列严格按交易日升序排列
        if "trade_date" in data.columns:
            data = data.sort("trade_date")

        # 提取当前标的名称与最新 Bar 交易时间戳
        symbol = data["symbol"].tail(1).item()
        bar_timestamp = data["trade_date"].tail(1).item() if "trade_date" in data.columns else None

        # 1. 调用数据分析层，为 DataFrame 追加 MACD 指标列
        df = calculate_macd(data)

        # 2. 提取最近两天的 MACD 柱 (macd_hist) 值
        hist_today = df["macd_hist"].tail(1).item()
        hist_yesterday = df["macd_hist"].tail(2).head(1).item()

        signals = []

        # 3. 信号生成逻辑
        # 金叉：昨天的柱子是负的，今天是正的（MACD线上穿Signal线）
        if hist_yesterday < 0 and hist_today > 0:
            signals.append(
                Signal(
                    symbol=symbol,
                    direction=SignalDirection.BUY,
                    target_weight=self.target_weight,
                    reason="MACD_GOLDEN_CROSS",
                    timestamp=bar_timestamp,
                )
            )
        # 死叉：昨天的柱子是正的，今天是负的（MACD线下穿Signal线）
        elif hist_yesterday > 0 and hist_today < 0:
            signals.append(
                Signal(
                    symbol=symbol,
                    direction=SignalDirection.SELL,
                    target_weight=0.0,  # 目标仓位 0 代表建议全部清仓
                    reason="MACD_DEAD_CROSS",
                    timestamp=bar_timestamp,
                )
            )

        return signals
