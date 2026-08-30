"""申万二级方向池产业趋势跟踪策略 (IndustryL2DirectionStrategy)。

面向全球共振方向池 6 个申万二级行业（半导体/通信设备/计算机设备/光伏设备/电池/乘用车），
季度调仓（默认 63 交易日）：
- 主排序：动量（默认 return_60d）Top K（默认 3），等权；
- 估值防守：pe_ttm_ew_percentile_5y 高位剔除（缺失放行）；
- 可选量价齐升门（require_qlq）：仅从「营收 + 净利 TTM 同比双正」行业选 TopK；
- 可选方向防守门（direction_gate）：方向高位（direction_score>阈值）× 非量价齐升
  行业剔除（对齐一级实证：方向追高反向，作防守不作进攻加分）。

数据源：``industry_l2_panel_daily``（阶段 1/3 产物，含 return_60d / 估值分位 /
revenue_growth_ttm / profit_growth_ttm / direction_score）。
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


class IndustryL2DirectionStrategy(BaseStrategy):
    """二级方向池策略：动量 Top3 + 估值防守，可选量价齐升门 / 方向防守门。"""

    def __init__(
        self,
        context: Context | None = None,
        *,
        top_k: int = 3,
        rebalance_period: int = 63,
        score_column: str = "return_60d",
        valuation_max: float = 90.0,
        require_qlq: bool = False,
        qlq_bonus: float = 0.0,
        direction_gate: bool = False,
        direction_high_threshold: float = 66.0,
        benchmark_symbol: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(context)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.valuation_max = float(valuation_max)
        self.require_qlq = bool(require_qlq)
        self.qlq_bonus = float(qlq_bonus)
        self.direction_gate = bool(direction_gate)
        self.direction_high_threshold = float(direction_high_threshold)
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.current_weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        """复位状态。"""
        self.current_weights = {}
        self._bar_count = 0

    def _qlq_expr(self) -> pl.Expr:
        """量价齐升：营收 + 净利 TTM 同比双正。"""
        return (pl.col("revenue_growth_ttm") > 0.0) & (pl.col("profit_growth_ttm") > 0.0)

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新截面数据并生成调仓信号。"""
        if data.is_empty():
            return []
        latest_date = data["trade_date"].max()
        if latest_date is None:
            return []
        latest = data.filter(pl.col("trade_date") == latest_date)
        if latest.is_empty() or self.score_column not in latest.columns:
            return []

        self._bar_count += 1
        # 季度调仓
        if self._bar_count > 1 and (self._bar_count - 1) % self.rebalance_period != 0:
            return []

        candidates = latest
        # 估值防守（pe5y 高位剔除，缺失放行）
        if "pe_ttm_ew_percentile_5y" in candidates.columns:
            candidates = candidates.filter(
                pl.col("pe_ttm_ew_percentile_5y").is_null()
                | (pl.col("pe_ttm_ew_percentile_5y") <= self.valuation_max)
            )
        # 量价齐升质量门（供需层，硬门）
        if self.require_qlq:
            if "revenue_growth_ttm" not in candidates.columns:
                return []
            candidates = candidates.filter(self._qlq_expr())
        # 方向防守门：方向高位 × 非量价齐升 → 剔除
        if self.direction_gate:
            if (
                "direction_score" in candidates.columns
                and "revenue_growth_ttm" in candidates.columns
            ):
                candidates = candidates.filter(
                    ~(
                        (pl.col("direction_score") > self.direction_high_threshold)
                        & (~self._qlq_expr())
                    )
                )

        ranked = (
            candidates.select(
                [
                    "industry_code",
                    "industry_name",
                    self.score_column,
                    "revenue_growth_ttm",
                    "profit_growth_ttm",
                ]
            )
            .drop_nulls(subset=[self.score_column])
            .with_columns(
                pl.when(self._qlq_expr())
                .then(pl.col(self.score_column) + self.qlq_bonus)
                .otherwise(pl.col(self.score_column))
                .alias("score")
            )
            .sort("score", descending=True)
        )
        if ranked.is_empty():
            return []

        top_rows = ranked.head(self.top_k).to_dicts()
        target_k = len(top_rows)
        weight_per_ind = round(1.0 / target_k, 4)
        ts = _coerce_timestamp(latest_date)

        new_weights: dict[str, float] = {}
        signals: list[Signal] = []
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
                    reason=(
                        f"二级方向池Top{self.top_k}: {name} ({self.score_column}={score:.1f})"
                        + (" [量价齐升]" if self.require_qlq else "")
                        + (" [方向防守]" if self.direction_gate else "")
                    ),
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
                        reason=f"二级方向池调仓剔除出Top{self.top_k}",
                        timestamp=ts,
                    )
                )

        self.current_weights = new_weights
        return signals


__all__ = ["IndustryL2DirectionStrategy"]
