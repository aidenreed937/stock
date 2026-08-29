from datetime import date, datetime

import polars as pl

from stock_core.utils.logger import logger
from stock_strategy.base import BaseStrategy
from stock_strategy.context import Context
from stock_strategy.signal import Signal, SignalDirection

_REQUIRED_COLUMNS = frozenset({"trade_date", "close", "panic_index", "overheat_index"})


def _coerce_timestamp(value: object) -> date | datetime | None:
    """把 trade_date 规整为 Signal 可用的时间戳。"""
    if isinstance(value, date | datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class MacroRiskV3Strategy(BaseStrategy):
    """宏观风控单宽基 V3 策略 (沪深300 + 智能分批 + 均线趋势过滤)。

    A (分批与趋势): 结合 Panic/Overheat 极值与 20 日均线 (MA20) 趋势右侧确认。
    B (单标的配置): 锚定 A 股大盘核心资产——沪深300 (000300.SH)，趋势基准同为沪深300。
    C (闲钱生息): 未使用的仓位全自动配置低风险固收资产 (如国债 ETF / 货币基金)。

    输入契约: 按 trade_date 升序的面板，需含 close / panic_index / overheat_index 列。
    """

    def __init__(
        self,
        context: Context | None = None,
        ma_window: int = 20,
        symbols: tuple[str, ...] | list[str] | None = None,
        initial_weights: dict[str, float] | None = None,
        benchmark_symbol: str | None = None,
        symbol: str | None = None,
        panic_threshold: float = 75.0,
        panic_entry_threshold: float = 65.0,
        overheat_threshold: float = 65.0,
    ) -> None:
        super().__init__(context)
        self.ma_window = ma_window
        self.symbol = symbol or (symbols[0] if symbols and len(symbols) > 0 else "000300.SH")
        self.benchmark_symbol = benchmark_symbol or "000300.SH"
        self.panic_threshold = float(panic_threshold)
        self.panic_entry_threshold = float(panic_entry_threshold)
        self.overheat_threshold = float(overheat_threshold)
        self.current_weight = 1.0  # 默认初始满仓

    def on_init(self) -> None:
        """复位跨回测状态，避免多次运行间仓位残留。"""
        self.current_weight = 1.0

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新数据，生成交易信号"""
        if data.is_empty() or len(data) < self.ma_window:
            return []
        if not _REQUIRED_COLUMNS.issubset(data.columns):
            logger.warning(
                "MacroRiskV3 数据缺少必需列: %s",
                sorted(_REQUIRED_COLUMNS - set(data.columns)),
            )
            return []

        data = data.sort("trade_date")

        # 计算 20 日均线
        close_prices = data["close"]
        ma20_val = close_prices.tail(self.ma_window).mean()
        if ma20_val is None or not isinstance(ma20_val, int | float):
            return []
        ma20 = float(ma20_val)

        latest = data.tail(1).to_dicts()[0]
        close_val = latest.get("close")
        panic_val = latest.get("panic_index")
        overheat_val = latest.get("overheat_index")
        if close_val is None or panic_val is None or overheat_val is None:
            return []
        close = float(close_val)
        panic = float(panic_val)
        overheat = float(overheat_val)
        timestamp = _coerce_timestamp(latest.get("trade_date"))

        target_weight = self.current_weight
        reason = ""

        # ==========================
        # V3 核心状态机逻辑 (沪深300)
        # ==========================
        if overheat > self.overheat_threshold and close < ma20:
            target_weight = 0.0
            reason = f"泡沫破裂逃顶 (Overheat={overheat:.1f}, 跌破MA{self.ma_window})"
        elif overheat > self.overheat_threshold and close >= ma20:
            target_weight = 0.5
            reason = f"泡沫膨胀减仓锁润 (Overheat={overheat:.1f}, 均线完好)"
        elif panic > self.panic_threshold:
            target_weight = 1.0
            reason = f"极度冰点满仓抄底 (Panic={panic:.1f})"
        elif panic > self.panic_entry_threshold:
            # 恐慌左侧：至少维持半仓托底，不主动减仓；真正加满仅在 panic > panic_threshold。
            target_weight = max(0.5, self.current_weight)
            reason = f"恐慌左侧分批建仓 (Panic={panic:.1f})"

        if target_weight == self.current_weight:
            return []

        if target_weight == 0.0:
            direction = SignalDirection.CLOSE
        elif target_weight > self.current_weight:
            direction = SignalDirection.BUY
        else:
            direction = SignalDirection.SELL

        self.current_weight = target_weight
        return [
            Signal(
                symbol=self.symbol,
                direction=direction,
                target_weight=target_weight,
                reason=reason,
                timestamp=timestamp,
            )
        ]
