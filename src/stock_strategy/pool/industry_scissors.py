"""申万行业供需景气剪刀差策略 (IndustrySupplyDemandScissorsStrategy)。

逻辑：
1. 锚定产业链真实定价权：毛利率与净利润增速逆势扩张 (ind_scissors > 60)；
2. 验证主力与外资共振抢筹：聪明资金流净流入 (ind_smart_flow > 50)；
3. 打满综合供需剪刀差与资金流最高的 Top K 行业。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import polars as pl

from stock_strategy.base import BaseStrategy
from stock_strategy.context import Context
from stock_strategy.signal import Signal, SignalDirection


def _coerce_timestamp(value: object) -> date | datetime | None:
    if isinstance(value, date | datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class IndustrySupplyDemandScissorsStrategy(BaseStrategy):
    """供需景气剪刀差与定价权行业轮动策略。"""

    def __init__(
        self,
        context: Context | None = None,
        *,
        top_k: int = 3,
        rebalance_period: int = 20,
        scissors_min: float = 60.0,
        scissors_weight: float = 0.40,
        momentum_weight: float = 0.35,
        smart_flow_weight: float = 0.25,
        benchmark_symbol: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(context)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.scissors_min = float(scissors_min)
        self.scissors_weight = float(scissors_weight)
        self.momentum_weight = float(momentum_weight)
        self.smart_flow_weight = float(smart_flow_weight)
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.current_weights: dict[str, float] = {}
        self._bar_count: int = 0

    def on_init(self) -> None:
        self.current_weights = {}
        self._bar_count = 0

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        if data.is_empty():
            return []

        latest_date = data["trade_date"].max()
        if latest_date is None:
            return []

        self._bar_count += 1
        if self._bar_count > 1 and (self._bar_count - 1) % self.rebalance_period != 0:
            return []

        latest_cross = data.filter(pl.col("trade_date") == latest_date)
        if latest_cross.is_empty():
            return []

        # 1. 过滤具备真实供需剪刀差 (毛利扩张) 的行业池
        valid = latest_cross.filter(pl.col("ind_scissors") >= self.scissors_min)
        if valid.is_empty():
            valid = latest_cross

        # 2. 计算复合得分 (剪刀差 + 景气动量确认 + 聪明资金流共振)
        scored = valid.with_columns(
            (
                self.scissors_weight * pl.col("ind_scissors").fill_null(50.0)
                + self.momentum_weight * pl.col("ind_momentum").fill_null(50.0)
                + self.smart_flow_weight * pl.col("ind_smart_flow").fill_null(50.0)
            ).alias("_scissors_score")
        ).sort("_scissors_score", descending=True)

        top_rows = scored.head(self.top_k).to_dicts()
        if not top_rows:
            return []

        target_k = len(top_rows)
        weight_per_ind = round(1.0 / target_k, 4)

        new_weights: dict[str, float] = {}
        signals: list[Signal] = []
        ts = _coerce_timestamp(latest_date)

        for row in top_rows:
            code = str(row["industry_code"])
            name = str(row.get("industry_name", code))
            sc_sc = float(row.get("ind_scissors", 0.0))
            flo_sc = float(row.get("ind_smart_flow", 0.0))
            new_weights[code] = weight_per_ind
            signals.append(
                Signal(
                    symbol=code,
                    direction=SignalDirection.BUY,
                    target_weight=weight_per_ind,
                    reason=f"供需剪刀差Top{self.top_k}: {name} (剪刀差={sc_sc:.1f}, 资金流={flo_sc:.1f})",
                    timestamp=ts,
                )
            )

        for old_code in self.current_weights:
            if old_code not in new_weights:
                signals.append(
                    Signal(
                        symbol=old_code,
                        direction=SignalDirection.CLOSE,
                        target_weight=0.0,
                        reason=f"剔除出剪刀差Top{self.top_k}",
                        timestamp=ts,
                    )
                )

        self.current_weights = new_weights
        return signals
