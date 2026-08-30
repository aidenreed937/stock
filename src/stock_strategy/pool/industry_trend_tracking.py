"""申万行业产业趋势跟踪策略 (IndustryTrendTrackingStrategy)。

逻辑（对齐已验证 milestone，样本外 Sharpe ≈ 0.39）：
1. 季度调仓（默认 63 个交易日）；
2. 按「环比趋势确认」得分（默认 trend_momentum）排序，追「景气方向」而非「景气高低」；
3. 打满 Top K（默认 3）行业，等权配置。

可选的产业趋势过滤（后续调优激活）：
- supply_demand_min：供需质量门，只买量价齐升（真需求驱动），剔除供给收缩假繁荣；
- crowding_max：拥挤度一票否决，剔除过热行业。
默认均不启用，以保证精确复现 milestone 基线。
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


class IndustryTrendTrackingStrategy(BaseStrategy):
    """产业趋势跟踪策略：季度调仓追景气方向，可选供需质量门与拥挤度防守。"""

    def __init__(
        self,
        context: Context | None = None,
        *,
        top_k: int = 3,
        rebalance_period: int = 63,
        score_column: str = "trend_momentum",
        supply_demand_min: float | None = None,
        crowding_max: float | None = None,
        direction_high_threshold: float | None = None,
        direction_quality_min: float = 50.0,
        benchmark_symbol: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(context)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.supply_demand_min = float(supply_demand_min) if supply_demand_min is not None else None
        self.crowding_max = float(crowding_max) if crowding_max is not None else None
        # 方向层象限过滤：方向高位 × 低供需质量（非量价齐升）→ 排除候选
        self.direction_high_threshold = (
            float(direction_high_threshold) if direction_high_threshold is not None else None
        )
        self.direction_quality_min = float(direction_quality_min)
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.current_weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        """复位状态。"""
        self.current_weights = {}
        self._bar_count = 0

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新截面数据并生成调仓信号。"""
        if data.is_empty():
            return []

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

        # 可选过滤：供需质量门（量价齐升）+ 拥挤度一票否决 + 方向层象限过滤
        candidates = latest_cross
        if self.supply_demand_min is not None and "supply_demand_score" in candidates.columns:
            candidates = candidates.filter(pl.col("supply_demand_score") >= self.supply_demand_min)
        if self.crowding_max is not None and "crowding_score" in candidates.columns:
            candidates = candidates.filter(pl.col("crowding_score") <= self.crowding_max)
        if (
            self.direction_high_threshold is not None
            and "direction_score" in candidates.columns
            and "supply_demand_score" in candidates.columns
        ):
            candidates = candidates.filter(
                ~(
                    (pl.col("direction_score") > self.direction_high_threshold)
                    & (pl.col("supply_demand_score") < self.direction_quality_min)
                )
            )

        ranked = (
            candidates.select(["industry_code", "industry_name", self.score_column])
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
                    reason=f"产业趋势Top{self.top_k}: {name} ({self.score_column}={score:.1f})",
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
                        reason=f"产业趋势调仓剔除出Top{self.top_k}",
                        timestamp=ts,
                    )
                )

        self.current_weights = new_weights
        return signals
