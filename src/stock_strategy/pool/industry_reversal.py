"""申万行业反拥挤逆向策略 (IndustryCrowdingReversalStrategy)。

逻辑：
1. 坚决规避拥挤踩踏：剔除拥挤度 > 85% 的过热行业；
2. 逆向潜伏低估值区：只在估值分位数处于安全区 (ind_valuation >= 80) 的行业中选股；
3. 优选中期动量初起的 Top K 行业等权配置。
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


class IndustryCrowdingReversalStrategy(BaseStrategy):
    """反拥挤逆向低估值行业轮动策略。"""

    def __init__(
        self,
        context: Context | None = None,
        *,
        top_k: int = 3,
        rebalance_period: int = 20,
        crowding_max: float = 85.0,
        valuation_min: float = 75.0,
        benchmark_symbol: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(context)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.crowding_max = float(crowding_max)
        self.valuation_min = float(valuation_min)
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

        # 1. 过滤高拥挤行业 (防踩踏)
        uncrowded = latest_cross.filter(pl.col("ind_crowding") <= self.crowding_max)
        if uncrowded.is_empty():
            uncrowded = latest_cross

        # 2. 筛选低估值安全边际行业 (ind_valuation >= valuation_min)
        candidates = uncrowded.filter(pl.col("ind_valuation") >= self.valuation_min)
        if candidates.is_empty():
            # 宽限回退: 按估值赔率排序选前 50%
            candidates = uncrowded.sort("ind_valuation", descending=True).head(15)

        # 3. 在候选池中选动量初起 Top K
        ranked = candidates.sort("ind_momentum", descending=True)
        top_rows = ranked.head(self.top_k).to_dicts()
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
            val_sc = float(row.get("ind_valuation", 0.0))
            cro_sc = float(row.get("ind_crowding", 0.0))
            new_weights[code] = weight_per_ind
            signals.append(
                Signal(
                    symbol=code,
                    direction=SignalDirection.BUY,
                    target_weight=weight_per_ind,
                    reason=f"反拥挤逆向Top{self.top_k}: {name} (估值={val_sc:.1f}, 拥挤={cro_sc:.1f})",
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
                        reason=f"剔除出逆向Top{self.top_k}",
                        timestamp=ts,
                    )
                )

        self.current_weights = new_weights
        return signals
