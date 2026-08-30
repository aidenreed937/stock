"""宏观风控「权益封顶 + 固收再平衡」组合层策略 (V5-rebalance)。

在 V5 资金博弈增强轮动策略（红利 + 创业板哑铃）之上叠加一层「权益仓封顶」：
权益腿目标仓位整体乘以 ``equity_cap``（默认 0.7），余量配置固收腿（默认 511010.SH
国债 ETF）。用于把 V5_etf 的深度回撤从约 -37% 压制到约 -25%（70/30）或 -18%（50/50），
研究口径与复算见 `references/v5_etf_fixed_income_rebalance.md`。

【执行语义】本策略输出的是「目标权重」，由 `MacroRiskRunner` 按「每日再平衡到目标
权重」语义复利（等价于每日把权益/固收比例拉回封顶值），比研究文档中的「季度再平衡」
更保守（权益权重永不超过 equity_cap，回撤更浅、收益略低）。若需严格季度再平衡需在
执行层引入权重漂移感知，当前不做。

与 V5 的唯一差异是「权益腿 × equity_cap + 固收补足」，其状态机（逃顶/抄底/乖离/聪明钱
过滤）完全复用 V5，不复制逻辑。
"""

from datetime import date, datetime

import polars as pl

from stock_strategy.base import BaseStrategy
from stock_strategy.context import Context
from stock_strategy.pool.macro_rotation_v5 import MacroRotationV5Strategy
from stock_strategy.signal import Signal, SignalDirection


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


class MacroRotationV5RebalanceStrategy(BaseStrategy):
    """宏观风控权益封顶 + 固收再平衡组合策略。"""

    def __init__(
        self,
        context: Context | None = None,
        ma_window: int = 20,
        symbols: tuple[str, ...] | list[str] | None = None,
        initial_weights: dict[str, float] | None = None,
        benchmark_symbol: str | None = None,
        equity_cap: float = 0.7,
        panic_threshold: float = 75.0,
        panic_entry_threshold: float = 65.0,
        overheat_threshold: float = 65.0,
        smart_filter_threshold: float = 40.0,
        bias_threshold: float = 0.15,
    ) -> None:
        super().__init__(context)
        self.ma_window = ma_window

        # 标的：前两个为权益腿（红利 + 创业板），第三个为固收腿
        self.sym_defensive = symbols[0] if symbols and len(symbols) > 0 else "510880.SH"
        self.sym_growth = symbols[1] if symbols and len(symbols) > 1 else "159915.SZ"
        self.fixed_symbol = symbols[2] if symbols and len(symbols) > 2 else "511010.SH"
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.equity_cap = float(equity_cap)

        # 内部复用 V5 权益腿状态机（不复制逻辑）
        self._v5 = MacroRotationV5Strategy(
            context=None,
            ma_window=ma_window,
            symbols=[self.sym_defensive, self.sym_growth],
            initial_weights=None,
            benchmark_symbol=benchmark_symbol,
            panic_threshold=panic_threshold,
            panic_entry_threshold=panic_entry_threshold,
            overheat_threshold=overheat_threshold,
            smart_filter_threshold=smart_filter_threshold,
            bias_threshold=bias_threshold,
        )

        self.initial_weights = (
            dict(initial_weights)
            if initial_weights
            else {
                self.sym_defensive: 0.5 * self.equity_cap,
                self.sym_growth: 0.5 * self.equity_cap,
                self.fixed_symbol: 1.0 - self.equity_cap,
            }
        )
        self.weights = dict(self.initial_weights)

    def on_init(self) -> None:
        """复位跨回测状态，避免多次运行间仓位残留。"""
        self._v5.on_init()
        self.weights = dict(self.initial_weights)

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新数据，生成「权益封顶 + 固收补足」的三标的轮动信号。"""
        if data.is_empty() or len(data) < self.ma_window:
            return []

        # 让 V5 处理权益腿（更新 _v5.weights 为红利/创业板目标）
        equity_signals = self._v5.on_bar(data)
        eq_target = self._v5.weights
        eq_total = sum(eq_target.values())
        scaled_eq_total = eq_total * self.equity_cap
        fixed_w = 1.0 - scaled_eq_total

        target = {sym: w * self.equity_cap for sym, w in eq_target.items()}
        target[self.fixed_symbol] = fixed_w

        v5_reason = equity_signals[0].reason if equity_signals else "持有"
        reason = f"{v5_reason} → 权益封顶{scaled_eq_total:.0%} (固收{fixed_w:.0%})"
        latest = data.tail(1).to_dicts()[0]
        timestamp = _coerce_timestamp(latest.get("trade_date"))

        signals: list[Signal] = []
        for sym, tgt_w in target.items():
            curr_w = self.weights.get(sym, 0.0)
            if abs(tgt_w - curr_w) < 1e-9:
                continue
            if tgt_w == 0.0:
                direction = SignalDirection.CLOSE
            elif tgt_w > curr_w:
                direction = SignalDirection.BUY
            else:
                direction = SignalDirection.SELL

            signals.append(
                Signal(
                    symbol=sym,
                    direction=direction,
                    target_weight=tgt_w,
                    reason=reason,
                    timestamp=timestamp,
                )
            )
            self.weights[sym] = tgt_w

        return signals
