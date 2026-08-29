"""宏观风控策略运行器：信号面板 → 信号序列与净值回测。

按交易日升序逐日把「截至当日」窗口喂给策略 ``on_bar``，累积得到可审计信号报告；
回测以目标权重持仓、现金（权重和 < 1 的余量）零收益，按指数收盘日收益复利。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

import polars as pl

from stock_strategy.base import BaseStrategy
from stock_strategy.runner import SignalReport
from stock_strategy.signal import Signal


def _trading_days(panel: pl.DataFrame) -> list[date]:
    return panel["trade_date"].unique(maintain_order=True).to_list()


def _daily_return(
    price_wide: pl.DataFrame,
    price_rows: dict[date, int],
    day: date,
    weights: Mapping[str, float],
) -> float:
    """组合当日收益：Σ 权重 × 标的日收益（缺失价格按 0，现金收益 0）。"""
    idx = price_rows.get(day)
    if idx is None or idx == 0 or not weights:
        return 0.0
    total = 0.0
    for sym, weight in weights.items():
        if weight == 0.0 or sym not in price_wide.columns:
            continue
        prev_close = price_wide[idx - 1, sym]
        curr_close = price_wide[idx, sym]
        if prev_close is None or curr_close is None:
            continue
        total += weight * (float(curr_close) / float(prev_close) - 1.0)
    return total


def _sync_strategy_positions(strategy: BaseStrategy, weights: Mapping[str, float]) -> None:
    """把策略内部持仓状态回写为执行层实际权重。

    死区过滤（rebalance_deadband）后，策略 ``on_bar`` 内部已按目标权重更新了
    自身状态（如 ``self.weights`` / ``self.current_weight``），但执行层因换手未达
    死区阈值不采纳该调仓。若不回写，策略与执行层持仓将脱节：后续 ``on_bar``
    会基于错误的"已调仓"状态生成信号。此函数在死区过滤分支调用，保证一致。
    """
    if hasattr(strategy, "weights") and isinstance(strategy.weights, dict):
        strategy.weights = dict(weights)
    if hasattr(strategy, "current_weight"):
        strategy.current_weight = float(next(iter(weights.values()), 0.0))


class MacroRiskRunner:
    """宏观策略研究运行器（支持微观交易成本与死区过滤）。"""

    def __init__(
        self,
        strategy: BaseStrategy,
        *,
        symbols: Sequence[str],
        initial_weights: Mapping[str, float] | None = None,
        strategy_name: str,
        strategy_version: str = "1.0.0",
        data_source: str = "tushare",
        commission_rate: float = 0.0,
        slippage_rate: float = 0.0,
        rebalance_deadband: float = 0.0,
    ) -> None:
        self.strategy = strategy
        self.symbols = tuple(symbols)
        self.initial_weights = dict(initial_weights or {})
        self.strategy_name = strategy_name
        self.strategy_version = strategy_version
        self.data_source = data_source
        self.commission_rate = max(float(commission_rate), 0.0)
        self.slippage_rate = max(float(slippage_rate), 0.0)
        self.rebalance_deadband = max(float(rebalance_deadband), 0.0)

    def run(self, panel: pl.DataFrame) -> SignalReport:
        """逐日推进策略并返回信号报告。"""
        self.strategy.on_init()
        signals: list[Signal] = []
        for day in _trading_days(panel):
            window = panel.filter(pl.col("trade_date") <= day)
            signals.extend(self.strategy.on_bar(window))
        return SignalReport(
            strategy_name=self.strategy_name,
            strategy_version=self.strategy_version,
            generated_at=datetime.now(),
            data_source=self.data_source,
            symbols=self.symbols,
            signals=tuple(signals),
        )

    def backtest(self, panel: pl.DataFrame, price_panel: pl.DataFrame) -> pl.DataFrame:
        """按目标权重回测，返回 ``trade_date / nav`` 净值序列（扣除真实交易摩擦与死区过滤）。"""
        self.strategy.on_init()
        if price_panel.is_empty():
            price_wide = pl.DataFrame(schema={"trade_date": pl.Date})
        else:
            price_wide = price_panel.pivot(
                on="symbol",
                index="trade_date",
                values="close",
                aggregate_function="first",
            ).sort("trade_date")
        price_rows = {d: i for i, d in enumerate(price_wide["trade_date"].to_list())}

        weights = dict(self.initial_weights)
        nav = 1.0
        records: list[float] = []
        days = _trading_days(panel)
        fee_rate = self.commission_rate + self.slippage_rate

        # 上一交易日收盘信号产生的待生效摩擦成本（T+1：信号 t 日生成、t+1 日生效并扣费）
        pending_fee: float = 0.0

        for i, day in enumerate(days):
            # 1. 首日为建仓日（当日收盘以初始权重建仓，nav 归一为 1.0），自次日起按持仓计算收益
            if i > 0:
                daily_gain = _daily_return(price_wide, price_rows, day, weights)
                nav *= 1.0 + daily_gain

            # 2. 扣减前一日信号在本日（T+1 生效日）产生的调仓摩擦
            if pending_fee > 0.0:
                nav *= max(1.0 - pending_fee, 0.0)
                pending_fee = 0.0

            # 3. 获取当日收盘信号（次日生效，T+1）
            window = panel.filter(pl.col("trade_date") <= day)
            new_signals = self.strategy.on_bar(window)
            if new_signals:
                tentative_weights = weights.copy()
                for sig in new_signals:
                    tentative_weights[sig.symbol] = float(sig.target_weight or 0.0)

                # 计算总换手权重变化
                all_syms = set(weights.keys()) | set(tentative_weights.keys())
                turnover = sum(
                    abs(tentative_weights.get(s, 0.0) - weights.get(s, 0.0)) for s in all_syms
                )

                # 死区过滤 (Deadband): 权重变动总和小于阈值时不触发真实调仓
                if turnover >= self.rebalance_deadband:
                    # 记录待扣摩擦（信号日不扣，T+1 生效日扣）
                    if fee_rate > 0.0 and turnover > 0.0:
                        pending_fee = turnover * fee_rate
                    weights = tentative_weights
                else:
                    # 死区过滤：执行层不调仓，策略内部状态需回写为实际权重，避免后续信号脱节
                    _sync_strategy_positions(self.strategy, weights)

            records.append(nav)

        return pl.DataFrame({"trade_date": days, "nav": records})


__all__ = ["MacroRiskRunner"]
