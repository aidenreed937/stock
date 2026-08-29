"""申万行业宏观元策略自适应动态路由器 (IndustryMetaRouterStrategy)。

逻辑：
1. 联动宏观风控双轨雷达 (Panic / Overheat) 与大盘 MA20 趋势；
2. 【相态 1：极度恐慌或破位熊市 (Panic > 75 或 Overheat > 65 & Close < MA20)】
   -> 100% 切换银行/煤炭/公用事业/食品饮料等低波红利防御行业；
3. 【相态 2：右侧多头高景气主升 (Close >= MA20 且 Overheat 适中 且 Panic < 65)】
   -> 100% 进攻电子/电力设备/计算机/通信等供需剪刀差与高成长行业 Top 3；
4. 【相态 3：常态震荡整理期】
   -> 50% 红利防御底仓 + 50% 景气成长进攻 (标准哑铃平衡)。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import polars as pl

from stock_strategy.base import BaseStrategy
from stock_strategy.context import Context
from stock_strategy.signal import Signal, SignalDirection

_DEFAULT_DEFENSIVE = ("801780.SI", "801950.SI", "801160.SI", "801120.SI")  # 银行/煤炭/电力/食品
_DEFAULT_GROWTH = ("801080.SI", "801730.SI", "801750.SI", "801770.SI")  # 电子/新能源/计算机/通信


def _coerce_timestamp(value: object) -> date | datetime | None:
    if isinstance(value, date | datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class IndustryMetaRouterStrategy(BaseStrategy):
    """宏观相态自适应行业轮动路由器。"""

    def __init__(
        self,
        context: Context | None = None,
        *,
        top_k: int = 3,
        rebalance_period: int = 20,
        ma_window: int = 20,
        panic_threshold: float = 75.0,
        overheat_threshold: float = 65.0,
        defensive_industries: tuple[str, ...] | list[str] | None = None,
        growth_industries: tuple[str, ...] | list[str] | None = None,
        benchmark_symbol: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(context)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.ma_window = int(ma_window)
        self.panic_threshold = float(panic_threshold)
        self.overheat_threshold = float(overheat_threshold)
        self.defensive_industries = tuple(defensive_industries or _DEFAULT_DEFENSIVE)
        self.growth_industries = tuple(growth_industries or _DEFAULT_GROWTH)
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

        # 提取宏观雷达指标（若存在）
        panic = (
            float(latest_cross["panic_index"][0])
            if "panic_index" in latest_cross.columns and latest_cross["panic_index"][0] is not None
            else 50.0
        )
        overheat = (
            float(latest_cross["overheat_index"][0])
            if "overheat_index" in latest_cross.columns
            and latest_cross["overheat_index"][0] is not None
            else 50.0
        )
        bench_close = (
            float(latest_cross["benchmark_close"][0])
            if "benchmark_close" in latest_cross.columns
            and latest_cross["benchmark_close"][0] is not None
            else 100.0
        )
        bench_ma20 = (
            float(latest_cross["benchmark_ma20"][0])
            if "benchmark_ma20" in latest_cross.columns
            and latest_cross["benchmark_ma20"][0] is not None
            else bench_close
        )

        new_weights: dict[str, float] = {}
        reason = ""

        # 状态机判定
        if panic > self.panic_threshold or (
            overheat > self.overheat_threshold and bench_close < bench_ma20
        ):
            # 状态 1: 恐慌避险/破位防守 -> 100% 切换红利防御行业
            w_def = round(1.0 / len(self.defensive_industries), 4)
            for code in self.defensive_industries:
                new_weights[code] = w_def
            reason = f"宏观避险防守(Panic={panic:.1f}, Overheat={overheat:.1f}): 切换红利防御"
        elif bench_close >= bench_ma20 and overheat <= self.overheat_threshold and panic < 65.0:
            # 状态 2: 右侧多头主升 -> 100% 切换剪刀差与成长赛道 Top 3
            growth_cross = latest_cross.filter(
                pl.col("industry_code").is_in(list(self.growth_industries))
                | (pl.col("ind_scissors") >= 50.0)
            ).sort("ind_momentum", descending=True)
            top_growth = growth_cross.head(self.top_k).to_dicts()
            if top_growth:
                w_g = round(1.0 / len(top_growth), 4)
                for row in top_growth:
                    new_weights[str(row["industry_code"])] = w_g
            else:
                w_g = round(1.0 / len(self.growth_industries), 4)
                for code in self.growth_industries:
                    new_weights[code] = w_g
            reason = "右侧多头主升(Close>=MA20): 打满高景气成长赛道"
        else:
            # 状态 3: 震荡整理 -> 50% 防御 + 50% 景气成长 (哑铃配置)
            w_def = round(0.5 / len(self.defensive_industries), 4)
            for code in self.defensive_industries:
                new_weights[code] = w_def

            mom_cross = (
                latest_cross.filter(~pl.col("industry_code").is_in(list(self.defensive_industries)))
                .sort("ind_momentum", descending=True)
                .head(2)
                .to_dicts()
            )
            if mom_cross:
                w_mom = round(0.5 / len(mom_cross), 4)
                for row in mom_cross:
                    new_weights[str(row["industry_code"])] = w_mom
            reason = "常态震荡整理: 50%红利防御 + 50%景气成长哑铃平衡"

        signals: list[Signal] = []
        ts = _coerce_timestamp(latest_date)

        for code, weight in new_weights.items():
            signals.append(
                Signal(
                    symbol=code,
                    direction=SignalDirection.BUY,
                    target_weight=weight,
                    reason=reason,
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
                        reason="元路由调仓平仓",
                        timestamp=ts,
                    )
                )

        self.current_weights = new_weights
        return signals
