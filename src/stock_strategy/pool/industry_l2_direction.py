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


def _qlq_expr() -> pl.Expr:
    """量价齐升：营收 + 净利 TTM 同比双正。"""
    return (pl.col("revenue_growth_ttm") > 0.0) & (pl.col("profit_growth_ttm") > 0.0)


def _filter_defense_candidates(
    candidates: pl.DataFrame,
    valuation_max: float = 90.0,
    require_qlq: bool = False,
    direction_gate: bool = False,
    direction_high_threshold: float = 66.0,
    capex_gate: bool = False,
    crowd_gate: bool = False,
    crowd_max: float = 85.0,
) -> pl.DataFrame:
    """执行估值、量价齐升、方向、资本开支与拥挤度防守层过滤。"""
    res = candidates
    if "pe_ttm_ew_percentile_5y" in res.columns:
        res = res.filter(
            pl.col("pe_ttm_ew_percentile_5y").is_null()
            | (pl.col("pe_ttm_ew_percentile_5y") <= valuation_max)
        )
    if require_qlq:
        if "revenue_growth_ttm" not in res.columns:
            return res.clear()
        res = res.filter(_qlq_expr())
    if direction_gate and "direction_score" in res.columns and "revenue_growth_ttm" in res.columns:
        res = res.filter(~((pl.col("direction_score") > direction_high_threshold) & (~_qlq_expr())))
    if capex_gate and "capex_growth_ttm" in res.columns:
        res = res.filter(
            pl.col("capex_growth_ttm").is_null()
            | (
                (pl.col("capex_growth_ttm") <= 60.0)
                & (pl.col("fix_assets_yoy").is_null() | (pl.col("fix_assets_yoy") <= 40.0))
            )
        )
    if crowd_gate and "crowding_score" in res.columns:
        res = res.filter(
            pl.col("crowding_score").is_null() | (pl.col("crowding_score") < crowd_max)
        )
    return res


class IndustryL2DirectionStrategy(BaseStrategy):
    """二级方向池策略：动量 Top3 + 估值防守，可选量价齐升门 / 方向防守门 / 组合防守门。"""

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
        capex_gate: bool = False,
        crowd_gate: bool = False,
        crowd_max: float = 85.0,
        panic_scale: float = 0.0,
        panic_thr: float = 65.0,
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
        self.capex_gate = bool(capex_gate)
        self.crowd_gate = bool(crowd_gate)
        self.crowd_max = float(crowd_max)
        self.panic_scale = float(panic_scale)
        self.panic_thr = float(panic_thr)
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.current_weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        """复位状态。"""
        self.current_weights = {}
        self._bar_count = 0

    def _panic_index(self, latest: pl.DataFrame) -> float:
        """当前截面恐慌指数（缺失回退 50）。"""
        if "panic_index" in latest.columns and latest["panic_index"][0] is not None:
            return float(latest["panic_index"][0])
        return 50.0

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
        if self._bar_count > 1 and (self._bar_count - 1) % self.rebalance_period != 0:
            return []

        ts = _coerce_timestamp(latest_date)
        if (
            0.0 < self.panic_scale < 1.0
            and self._panic_index(latest) > self.panic_thr
            and self.current_weights
        ):
            panic_weights = {code: w * self.panic_scale for code, w in self.current_weights.items()}
            panic_signals = [
                Signal(
                    symbol=code,
                    direction=SignalDirection.BUY,
                    target_weight=weight,
                    reason=f"宏观恐慌降仓 (panic>{self.panic_thr:.0f})",
                    timestamp=ts,
                )
                for code, weight in panic_weights.items()
            ]
            self.current_weights = panic_weights
            return panic_signals

        candidates = _filter_defense_candidates(
            latest,
            valuation_max=self.valuation_max,
            require_qlq=self.require_qlq,
            direction_gate=self.direction_gate,
            direction_high_threshold=self.direction_high_threshold,
            capex_gate=self.capex_gate,
            crowd_gate=self.crowd_gate,
            crowd_max=self.crowd_max,
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
                pl.when(_qlq_expr())
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
