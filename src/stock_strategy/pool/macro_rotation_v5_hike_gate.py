"""宏观风控「加息周期」非对称防守闸门策略 (V5-rebalance + Hike-Gate)。

在 ``MacroRotationV5RebalanceStrategy``（V5 权益状态机 × 常数权益封顶 + 固收再平衡）
之上叠加一层"利率上行周期"防守闸门：

- 依据（旧口径实证留档见 ``references/ffr_cycle_factor_research.md``；基于月频 FEDFUNDS，DFF 换源后尚未复验）：``ffr_chg_6m``
  加息期（|Δ6m|≥0.25pp）973 日 fwd60 中位 -3.01%/胜率 32%，降息期 +3.00%/73%；
  加息尾部（周期 19 月+）最痛（2015 周期 -2.99%/37%、2022 周期 -5.25%/17%）。
- 语义：``ffr_chg_6m_score``（0-100 滚动历史分位，raw 方向 = 高分位即加息风险）
  当日 ≥ ``hike_gate_threshold`` 时视为处于"加息周期中"，权益总封顶从 ``equity_cap``
  降至 ``hike_cap``，余量转固收；分位回落 < 阈值后自动恢复 ``equity_cap``。
  无状态滞回：当前生产 score 基于日频 DFF；旧口径月频样本的阈值分布与停加表现不能直接外推，
  DFF 下的门控效果以重新生成的策略报告和审计产物为准。
- 定位：**非对称防守增强层（2026-09-04 正式启用，只防守不进攻，非 alpha）**；与 slow-top-
  divergence 闸门相互独立（一个管"慢速顶背离"，一个管"利率周期"），可分别开关。

与 V5-rebalance 的唯一差异是"权益封顶根据加息闸门动态在 equity_cap 与 hike_cap 间切换"，
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

# 加息闸门信号所需的因子列（需在 strategy.panel_extra_cols 声明）
_HIKE_FACTOR_COL = "ffr_chg_6m_score"


class MacroRotationV5HikeGateStrategy(MacroRotationV5RebalanceStrategy):
    """V5-rebalance + 加息周期非对称防守闸门策略。"""

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
        hike_cap: float = 0.35,
        hike_gate_threshold: float = 60.0,
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
        self.hike_cap = float(hike_cap)
        self.hike_gate_threshold = float(hike_gate_threshold)

    def _hike_gate_active(self, history: pl.DataFrame) -> bool:
        """加息闸门：``ffr_chg_6m_score`` 高分位时激活。

        ``ffr_chg_6m_score`` 本身已是 0-100 滚动历史分位排名（管线 ``rolling_percentile``
        产出，窗口 1250），故直接用绝对高位判断、不重复做二次滚动分位。历史数据
        （含当日）即可，因果、无前视；因子列缺失时 fail-closed 为不激活。
        """
        if _HIKE_FACTOR_COL not in history.columns:
            return False
        latest = history.drop_nulls(_HIKE_FACTOR_COL).tail(1)
        if latest.is_empty():
            return False
        return float(latest[_HIKE_FACTOR_COL][0]) >= self.hike_gate_threshold

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        if data.is_empty() or len(data) < self.ma_window:
            return []

        # 让 V5 处理权益腿（更新 _v5.weights 为红利/创业板目标）
        equity_signals = self._v5.on_bar(data)
        eq_target = self._v5.weights
        eq_total = sum(eq_target.values())

        gate_on = self._hike_gate_active(data)
        cap = self.hike_cap if gate_on else self.equity_cap
        scaled_eq_total = eq_total * cap
        fixed_w = 1.0 - scaled_eq_total

        target = {sym: w * cap for sym, w in eq_target.items()}
        target[self.fixed_symbol] = fixed_w

        v5_reason = equity_signals[0].reason if equity_signals else "持有"
        gate_txt = (
            f"加息闸门ON(权益封顶{cap:.0%})" if gate_on else f"加息闸门OFF(权益封顶{cap:.0%})"
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


__all__ = ["MacroRotationV5HikeGateStrategy"]
