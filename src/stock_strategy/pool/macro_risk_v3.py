from datetime import date, datetime

import polars as pl

from stock_strategy.base import BaseStrategy
from stock_strategy.context import Context
from stock_strategy.signal import Signal, SignalDirection


class MacroRiskV3Strategy(BaseStrategy):
    """宏观风控单宽基 V3 策略 (沪深300 + 智能分批 + 均线趋势过滤)。

    A (分批与趋势): 结合 Panic/Overheat 极值与 20 日均线 (MA20) 趋势右侧确认。
    B (单标的配置): 锚定 A 股大盘核心资产——沪深300 (000300.SH)。
    C (闲钱生息): 未使用的仓位全自动配置低风险固收资产 (如国债 ETF / 货币基金)。
    """

    def __init__(self, context: Context | None = None, ma_window: int = 20) -> None:
        super().__init__(context)
        self.ma_window = ma_window
        self.symbol = "000300.SH"  # 升级锚定大盘核心宽基：沪深300
        self.current_weight = 1.0  # 默认初始满仓

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新数据，生成交易信号"""
        if data.is_empty() or len(data) < self.ma_window:
            return []

        # 提取最新一天的截面数据
        latest = data.tail(1).to_dicts()[0]

        # 计算 20 日均线
        close_prices = data["close"]
        ma20_val = close_prices.tail(self.ma_window).mean()
        if ma20_val is None or not isinstance(ma20_val, int | float):
            return []
        ma20 = float(ma20_val)

        close = float(latest.get("close", 0.0))
        panic = float(latest.get("panic_index", 0.0))
        overheat = float(latest.get("overheat_index", 0.0))
        trade_date_val = latest.get("trade_date")

        timestamp: date | datetime | None = None
        if isinstance(trade_date_val, date | datetime):
            timestamp = trade_date_val

        target_weight = self.current_weight
        reason = ""
        direction = SignalDirection.CLOSE

        # ==========================
        # V3 核心状态机逻辑 (沪深300)
        # ==========================
        if overheat > 65 and close < ma20:
            target_weight = 0.0
            reason = f"泡沫破裂逃顶 (Overheat={overheat:.1f}, 跌破MA20)"
            direction = SignalDirection.CLOSE

        elif overheat > 65 and close >= ma20:
            target_weight = 0.5
            reason = f"泡沫膨胀减仓锁润 (Overheat={overheat:.1f}, 均线完好)"
            direction = SignalDirection.SELL

        elif panic > 75:
            target_weight = 1.0
            reason = f"极度冰点满仓抄底 (Panic={panic:.1f})"
            direction = SignalDirection.BUY

        elif panic > 65:
            target_weight = max(0.5, self.current_weight)  # 左侧至少维持半仓
            reason = f"恐慌左侧分批建仓 (Panic={panic:.1f})"
            direction = SignalDirection.BUY

        # 生成标准交易信号
        signals: list[Signal] = []
        if target_weight != self.current_weight:
            if target_weight == 0.0:
                direction = SignalDirection.CLOSE
            elif target_weight > self.current_weight:
                direction = SignalDirection.BUY
            else:
                direction = SignalDirection.SELL

            signals.append(
                Signal(
                    symbol=self.symbol,
                    direction=direction,
                    target_weight=target_weight,
                    reason=reason,
                    timestamp=timestamp,
                )
            )
            self.current_weight = target_weight

        return signals
