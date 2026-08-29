"""申万行业纯景气动量轮动策略 (IndustryMomentumRotationStrategy)。

逻辑：
1. 定期调仓（默认每 20 个交易日）；
2. 提取当前截面 31 行业景气动量得分 (ind_momentum) 或复合中观得分；
3. 打满得分最高的 Top K（默认 K=3）行业，等权配置 (各 1/K)。
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


class IndustryMomentumRotationStrategy(BaseStrategy):
    """纯高景气动量行业轮动策略。"""

    def __init__(
        self,
        context: Context | None = None,
        *,
        top_k: int = 3,
        rebalance_period: int = 20,
        score_column: str = "ind_momentum",
        benchmark_symbol: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(context)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.current_weights: dict[str, float] = {}
        self._bar_count: int = 0

    def on_init(self) -> None:
        """复位状态。"""
        self.current_weights = {}
        self._bar_count = 0

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新截面数据并生成调仓信号。"""
        if data.is_empty():
            return []

        # 仅取当日截面
        latest_date = data["trade_date"].max()
        if latest_date is None:
            return []

        self._bar_count += 1
        # 首次或满足调仓周期时触发调仓
        if self._bar_count > 1 and (self._bar_count - 1) % self.rebalance_period != 0:
            return []

        latest_cross = data.filter(pl.col("trade_date") == latest_date)
        if latest_cross.is_empty() or self.score_column not in latest_cross.columns:
            return []

        # 排序选出 Top K
        ranked = (
            latest_cross.select(["industry_code", "industry_name", self.score_column])
            .drop_nulls(subset=[self.score_column])
            .sort(self.score_column, descending=True)
        )
        if ranked.is_empty():
            return []

        top_rows = ranked.head(self.top_k).to_dicts()
        target_k = len(top_rows)
        weight_per_ind = round(1.0 / target_k, 4)

        new_weights: dict[str, float] = {}
        signals: list[Signal] = []
        ts = _coerce_timestamp(latest_date)

        for row in top_rows:
            code = str(row["industry_code"])
            name = str(row.get("industry_name", code))
            score = float(row[self.score_column])
            new_weights[code] = weight_per_ind
            signals.append(
                Signal(
                    symbol=code,
                    direction=SignalDirection.BUY,
                    target_weight=weight_per_ind,
                    reason=f"高景气动量Top{self.top_k}: {name} ({self.score_column}={score:.1f})",
                    timestamp=ts,
                )
            )

        # 对不再持有的旧标的发平仓信号
        for old_code in self.current_weights:
            if old_code not in new_weights:
                signals.append(
                    Signal(
                        symbol=old_code,
                        direction=SignalDirection.CLOSE,
                        target_weight=0.0,
                        reason=f"调仓剔除出Top{self.top_k}",
                        timestamp=ts,
                    )
                )

        self.current_weights = new_weights
        return signals
