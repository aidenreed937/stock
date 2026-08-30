"""宏观风控「回撤深度确认抄底」变体 (V5-rebalance-DD)。

在 ``MacroRotationV5RebalanceStrategy``（权益封顶 + 固收再平衡）基础上，对
「极度冰点满仓创业板 (Panic > 75)」分支叠加**回撤深度确认**：

- 触发满仓时，若基准（中证全指）距前 120 交易日高点回撤不足 ``panic_dd_full_threshold``
  （默认 15%），判定为「情绪极值但价格未跌透」的高位恐慌，**降级为恐慌左侧分批**
  （红利 20% + 创业板 50%），避免在半山腰满仓接飞刀；
- 回撤 ≥ 阈值（深底）才允许满仓创业板，保留 V 反行情的全部收益。

动机：全样本复算显示 ``Panic > 75`` 触发时的市场位置决定后验——距高点回撤 >30% 的
16 次后 60 日胜率 100%、均收益 +19.95%；而回撤不足 5% 的 3 次全败（胜率 0%）。
2026-07 五次触发均落在 -6.6% ~ -15.7% 的中级调整区（非深底），连续接飞刀。

本变体仅修改「冰点满仓」分支，其余状态机（逃顶/乖离/聪明钱过滤/权益封顶/固收）完全复用。
"""

from datetime import date, datetime

import polars as pl

from stock_strategy.context import Context
from stock_strategy.pool.macro_rotation_v5_rebalance import MacroRotationV5RebalanceStrategy
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


class MacroRotationV5RebalanceDDStrategy(MacroRotationV5RebalanceStrategy):
    """宏观风控回撤深度确认抄底（权益封顶 + 固收再平衡 + 冰点满仓回撤确认）。"""

    def __init__(
        self,
        context: Context | None = None,
        ma_window: int = 20,
        symbols: tuple[str, ...] | list[str] | None = None,
        initial_weights: dict[str, float] | None = None,
        benchmark_symbol: str | None = None,
        equity_cap: float = 0.7,
        panic_dd_full_threshold: float = 0.15,
        panic_threshold: float = 75.0,
        panic_entry_threshold: float = 65.0,
        overheat_threshold: float = 65.0,
        smart_filter_threshold: float = 40.0,
        bias_threshold: float = 0.15,
    ) -> None:
        super().__init__(
            context=context,
            ma_window=ma_window,
            symbols=symbols,
            initial_weights=initial_weights,
            benchmark_symbol=benchmark_symbol,
            equity_cap=equity_cap,
            panic_threshold=panic_threshold,
            panic_entry_threshold=panic_entry_threshold,
            overheat_threshold=overheat_threshold,
            smart_filter_threshold=smart_filter_threshold,
            bias_threshold=bias_threshold,
        )
        self.panic_dd_full_threshold = float(panic_dd_full_threshold)

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新数据；Panic>75 满仓分支叠加回撤深度确认。"""
        if data.is_empty() or len(data) < self.ma_window:
            return []

        # 让 V5 处理权益腿（更新 _v5.weights 为红利/创业板目标）
        equity_signals = self._v5.on_bar(data)
        eq_target = self._v5.weights

        # 回撤深度确认：V5 触发「满仓创业板」但基准回撤不足 → 降级为恐慌左侧分批
        downgraded = False
        dd = 0.0
        is_full_growth = (
            eq_target.get(self.sym_growth, 0.0) >= 0.99
            and eq_target.get(self.sym_defensive, 0.0) < 0.01
        )
        if is_full_growth:
            closes = data["close"].to_list()
            if len(closes) >= 121:
                hi120 = max(closes[-121:-1])  # 不含当日的前 120 日高点
                dd = closes[-1] / hi120 - 1 if hi120 > 0 else 0.0
                if dd > -self.panic_dd_full_threshold:
                    # 回撤不足：满仓降级为分批（红利 20% + 创业板 50%）
                    self._v5.weights = {self.sym_defensive: 0.2, self.sym_growth: 0.5}
                    eq_target = self._v5.weights
                    downgraded = True

        eq_total = sum(eq_target.values())
        scaled_eq_total = eq_total * self.equity_cap
        fixed_w = 1.0 - scaled_eq_total

        target = {sym: w * self.equity_cap for sym, w in eq_target.items()}
        target[self.fixed_symbol] = fixed_w

        if downgraded:
            v5_reason = (
                f"冰点满仓降级为分批 (回撤{dd:.1%}不足{self.panic_dd_full_threshold:.0%}, Panic>75)"
            )
        else:
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
