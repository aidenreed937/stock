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

        for i, day in enumerate(days):
            # 1. 首日为建仓日（当日收盘以初始权重建仓，nav 归一为 1.0），自次日起按持仓计算收益
            if i > 0:
                daily_gain = _daily_return(price_wide, price_rows, day, weights)
                nav *= 1.0 + daily_gain

            # 2. 获取当日收盘信号（次日生效，T+1）
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
                    # 扣除换手交易摩擦 (佣金 + 冲击滑点)
                    if fee_rate > 0.0 and turnover > 0.0:
                        friction_cost = turnover * fee_rate
                        nav *= max(1.0 - friction_cost, 0.0)
                    weights = tentative_weights

            records.append(nav)

        return pl.DataFrame({"trade_date": days, "nav": records})


__all__ = ["MacroRiskRunner"]
