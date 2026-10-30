"""宏观风控「中期顶背离」慢速减仓闸门策略 (V5-rebalance + Slow Top-Divergence Gate)。

在 ``MacroRotationV5RebalanceStrategy``（V5 权益状态机 × 常数权益封顶 + 固收再平衡）
之上叠加一层"中期顶背离"慢速减仓闸门：

- 依据（方法论 §7.4 / §5.3 / IC 切片实证）：`copper_gold_score`(60D IC -0.33) 与
  `cb_price_score`(60D IC -0.209) 是最强、最稳的单因子，但属**慢变量**（信号集中在 60D）；
  直接混入 overheat_index 服务 20D 短线防守已被证伪（§5.3 全面劣化）。故独立合成慢速闸门。
- 语义：`dim_slow = mean(copper_gold_score, cb_price_score)`（二者均为 0-100 滚动历史
  分位排名）；当 `dim_slow >= gate_threshold`（绝对高位，如 80）时，把权益总封顶从
  `equity_cap` 降至 `gate_cap`，余量转固收；分位回落 < `gate_off_threshold` 后恢复 `equity_cap`。
- 定位：**回撤抑制/防守增强层，非 alpha 增强**（Walk-Forward OOS 验证：整体夏普 +0.1、
  防守市 MDD 显著收窄，但进攻端 CAGR 无稳定超额）。

与 V5-rebalance 的唯一差异是"权益封顶根据慢速顶背离动态在 equity_cap 与 gate_cap 间切换"，
其余状态机（逃顶/抄底/乖离/聪明钱过滤）完全复用 V5-rebalance，不复制逻辑。
"""

from __future__ import annotations

import polars as pl

from stock_strategy.context import Context
from stock_strategy.pool.macro_rotation_v5_rebalance import (
    MacroRotationV5RebalanceStrategy,
    _coerce_timestamp,
)
from stock_strategy.signal import Signal, SignalDirection

# 慢速顶背离信号表征所需的因子列（需在 strategy.panel_extra_cols 声明）
_GATE_FACTOR_COLS = ("copper_gold_score", "cb_price_score")


class MacroSlowTopDivergenceStrategy(MacroRotationV5RebalanceStrategy):
    """V5-rebalance + 中期顶背离慢速减仓闸门策略。"""

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
        gate_cap: float = 0.30,
        gate_threshold: float = 80.0,
        gate_off_threshold: float = 60.0,
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
        self.gate_cap = float(gate_cap)
        self.gate_threshold = float(gate_threshold)
        self.gate_off_threshold = float(gate_off_threshold)

    def _slow_gate_active(self, history: pl.DataFrame) -> bool:
        """慢速顶背离闸门：dim_slow 高分位时激活（回落后解除）。

        ``copper_gold_score`` / ``cb_price_score`` 本身已是 0-100 滚动历史分位排名
        （管线 ``rolling_percentile`` 产出，窗口 1250），故**直接用绝对高位判断**、
        **不重复做二次滚动分位**（对已分位值再分位会退化为常数高百分位）。历史数据
        （含当日）即可，因果、无前视；因子列缺失时 fail-closed 为不激活。
        """
        cols = [c for c in _GATE_FACTOR_COLS if c in history.columns]
        if len(cols) < len(_GATE_FACTOR_COLS):
            return False
        latest = history.drop_nulls(cols).tail(1)
        if latest.is_empty():
            return False
        row = latest.to_dicts()[0]
        dim_slow = (float(row["copper_gold_score"]) + float(row["cb_price_score"])) / 2.0
        return dim_slow >= self.gate_threshold

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        if data.is_empty() or len(data) < self.ma_window:
            return []

        # 让 V5 处理权益腿（更新 _v5.weights 为红利/创业板目标）
        equity_signals = self._v5.on_bar(data)
        eq_target = self._v5.weights
        eq_total = sum(eq_target.values())

        gate_on = self._slow_gate_active(data)
        cap = self.gate_cap if gate_on else self.equity_cap
        scaled_eq_total = eq_total * cap
        fixed_w = 1.0 - scaled_eq_total

        target = {sym: w * cap for sym, w in eq_target.items()}
        target[self.fixed_symbol] = fixed_w

        v5_reason = equity_signals[0].reason if equity_signals else "持有"
        gate_txt = (
            f"中期顶背离闸门ON(权益封顶{cap:.0%})"
            if gate_on
            else f"中期顶背离闸门OFF(权益封顶{cap:.0%})"
        )
        reason = f"{v5_reason} → {gate_txt} (权益{scaled_eq_total:.0%}/固收{fixed_w:.0%})"
        latest = data.tail(1).to_dicts()[0]
        timestamp = _coerce_timestamp(latest.get("trade_date"))

        signals: list[Signal] = []
        for sym, tgt_w in target.items():
            curr_w = self.weights.get(sym, 0.0)
            if abs(tgt_w - curr_w) < 1e-9:
                continue
            direction = (
                SignalDirection.CLOSE
                if tgt_w == 0.0
                else (SignalDirection.BUY if tgt_w > curr_w else SignalDirection.SELL)
            )
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


__all__ = ["MacroSlowTopDivergenceStrategy"]
