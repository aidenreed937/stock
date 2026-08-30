"""宏观大类资产全天候自适应轮动策略 (MacroAllWeatherStrategy)。

融合宏观风控双轨雷达 (Panic / Overheat)、聪明钱与产业资本托底 (smart_money / dim_corporate)、
跨资产估值 (dim_cross_asset) 与 20日均线 (MA20) 趋势，在 5 大类资产间全天候自适应动态切换：
1. 【相态 4：狂热泡沫破裂 (Overheat > 65 & Close < MA20)】
   - 权益仓位降为 0%，配置 60% 国债 ETF + 40% 黄金 ETF 刚性避险与吃息；
2. 【相态 1：极度恐慌与聪明钱/产业底共振 (Panic > 75 或 Panic > 65 & (聪明钱>=80 或 回购>=80))】
   - 固收与黄金仓位降为 0%；
   - 左侧探底 (Close < MA20)：配置 40% 沪深300 ETF + 30% 红利 ETF + 30% 创业板 ETF (对齐托底防踩踏)；
   - 右侧突破 (Close >= MA20)：配置 70% 创业板 ETF + 30% 沪深300 ETF (打满弹性主升)；
3. 【相态 3：狂热泡沫中继 (Overheat > 65 & Close >= MA20)】
   - 配置 40% 红利 ETF + 30% 国债 ETF + 30% 黄金 ETF 锁润防守；
4. 【相态 2：估值大底探底 (Panic > 65 或 Valuation <= 15%)】
   - 跨资产均衡锁仓：30% 红利 ETF + 30% 沪深300 ETF + 20% 创业板 ETF + 20% 国债 ETF；
5. 【相态 0：常态中枢趋势自适应】
   - 保持状态机持仓延续，避免震荡市频繁调仓摩擦。
"""

from __future__ import annotations

from datetime import date, datetime

import polars as pl

from stock_core.utils.logger import logger
from stock_strategy.base import BaseStrategy
from stock_strategy.context import Context
from stock_strategy.signal import Signal, SignalDirection

_REQUIRED_COLUMNS = frozenset({"trade_date", "close", "panic_index", "overheat_index"})


def _coerce_timestamp(value: object) -> date | datetime | None:
    """把 trade_date 规整为 Signal 可用的时间戳。"""
    if isinstance(value, date | datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class MacroAllWeatherStrategy(BaseStrategy):
    """宏观大类资产全天候自适应轮动策略。"""

    def __init__(
        self,
        context: Context | None = None,
        ma_window: int = 20,
        symbols: tuple[str, ...] | list[str] | None = None,
        initial_weights: dict[str, float] | None = None,
        benchmark_symbol: str | None = None,
        panic_threshold: float = 75.0,
        panic_entry_threshold: float = 65.0,
        overheat_threshold: float = 65.0,
        smart_support_threshold: float = 80.0,
        repurchase_score_threshold: float = 80.0,
        valuation_threshold: float = 15.0,
    ) -> None:
        super().__init__(context)
        self.ma_window = ma_window

        # 5 大核心资产 (默认: 红利 ETF, 创业板 ETF, 300 ETF, 国债 ETF, 黄金 ETF)
        self.sym_defensive = symbols[0] if symbols and len(symbols) > 0 else "510880.SH"
        self.sym_growth = symbols[1] if symbols and len(symbols) > 1 else "159915.SZ"
        self.sym_core = symbols[2] if symbols and len(symbols) > 2 else "510300.SH"
        self.sym_bond = symbols[3] if symbols and len(symbols) > 3 else "511010.SH"
        self.sym_gold = symbols[4] if symbols and len(symbols) > 4 else "518880.SH"

        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.panic_threshold = float(panic_threshold)
        self.panic_entry_threshold = float(panic_entry_threshold)
        self.overheat_threshold = float(overheat_threshold)
        self.smart_support_threshold = float(smart_support_threshold)
        self.repurchase_score_threshold = float(repurchase_score_threshold)
        self.valuation_threshold = float(valuation_threshold)

        self.initial_weights = (
            dict(initial_weights)
            if initial_weights
            else {
                self.sym_defensive: 0.3,
                self.sym_growth: 0.3,
                self.sym_core: 0.2,
                self.sym_bond: 0.2,
                self.sym_gold: 0.0,
            }
        )
        self.weights = dict(self.initial_weights)

    def on_init(self) -> None:
        """复位跨回测状态。"""
        self.weights = dict(self.initial_weights)

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """根据宏观全天候相态状态机执行动态跨资产自适应路由。"""
        if data.is_empty() or len(data) < self.ma_window:
            return []
        if not _REQUIRED_COLUMNS.issubset(data.columns):
            logger.warning(
                "MacroAllWeather 数据缺少必需列: %s",
                sorted(_REQUIRED_COLUMNS - set(data.columns)),
            )
            return []

        data = data.sort("trade_date")

        close_prices = data["close"]
        ma20_val = close_prices.tail(self.ma_window).mean()
        if ma20_val is None or not isinstance(ma20_val, int | float):
            return []
        ma20 = float(ma20_val)

        latest = data.tail(1).to_dicts()[0]
        close_val = latest.get("close")
        panic_val = latest.get("panic_index")
        overheat_val = latest.get("overheat_index")
        if close_val is None or panic_val is None or overheat_val is None:
            return []
        close = float(close_val)
        panic = float(panic_val)
        overheat = float(overheat_val)

        smart_score_val = latest.get("smart_money_pct")
        smart_score = float(smart_score_val) if isinstance(smart_score_val, int | float) else None

        rep_score_val = latest.get("repurchase_score")
        rep_score = float(rep_score_val) if isinstance(rep_score_val, int | float) else None

        dim_corp_val = latest.get("dim_corporate")
        dim_corp = float(dim_corp_val) if isinstance(dim_corp_val, int | float) else None

        dim_val_raw = latest.get("dim_valuation")
        dim_val = float(dim_val_raw) if isinstance(dim_val_raw, int | float) else None

        timestamp = _coerce_timestamp(latest.get("trade_date"))

        target = self.weights.copy()
        reason = ""

        # 是否触发聪明钱/产业资本强托底共振
        has_support_resonance = (
            (smart_score is not None and smart_score >= self.smart_support_threshold)
            or (rep_score is not None and rep_score >= self.repurchase_score_threshold)
            or (dim_corp is not None and dim_corp >= self.repurchase_score_threshold)
        )

        # ==============================================================
        # 全天候 5 大相态动态资产路由
        # ==============================================================

        # 相态 4：狂热泡沫破裂 -> 0% 权益，切换至 60% 国债 ETF + 40% 黄金 ETF 避险
        if overheat > self.overheat_threshold and close < ma20:
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 0.0
            target[self.sym_core] = 0.0
            target[self.sym_bond] = 0.6
            target[self.sym_gold] = 0.4
            reason = f"相态4: 泡沫破裂转债金避险 (Overheat={overheat:.1f}, 跌破MA{self.ma_window})"

        # 相态 1：极度恐慌与聪明钱/产业共振 -> 清仓避险资产，打满权益弹性
        elif panic > self.panic_threshold or (
            panic > self.panic_entry_threshold and has_support_resonance
        ):
            target[self.sym_bond] = 0.0
            target[self.sym_gold] = 0.0
            if close < ma20:
                # 左侧探底：沪深300与红利压舱托底
                target[self.sym_core] = 0.4
                target[self.sym_defensive] = 0.3
                target[self.sym_growth] = 0.3
                reason = f"相态1: 恐慌冰点多主体托底左侧防踩踏 (Panic={panic:.1f})"
            else:
                # 右侧突破：打满高贝塔成长弹性
                target[self.sym_growth] = 0.7
                target[self.sym_core] = 0.3
                target[self.sym_defensive] = 0.0
                reason = f"相态1: 恐慌出清右侧突破打满成长 (Panic={panic:.1f})"

        # 相态 3：狂热泡沫膨胀中继 -> 40% 红利 + 30% 国债 + 30% 黄金 锁润防守
        elif overheat > self.overheat_threshold and close >= ma20:
            target[self.sym_defensive] = 0.4
            target[self.sym_growth] = 0.0
            target[self.sym_core] = 0.0
            target[self.sym_bond] = 0.3
            target[self.sym_gold] = 0.3
            reason = f"相态3: 泡沫膨胀切红利与债金锁润 (Overheat={overheat:.1f})"

        # 相态 2：估值大底探底 -> 跨资产均衡锁仓
        elif panic > self.panic_entry_threshold or (
            dim_val is not None and dim_val <= self.valuation_threshold
        ):
            target[self.sym_defensive] = 0.3
            target[self.sym_core] = 0.3
            target[self.sym_growth] = 0.2
            target[self.sym_bond] = 0.2
            target[self.sym_gold] = 0.0
            reason = f"相态2: 估值大底跨资产均衡锁仓 (Panic={panic:.1f})"

        # 相态 0：常态中枢区间保持状态机持仓延续
        else:
            pass

        signals: list[Signal] = []
        for sym, tgt_w in target.items():
            curr_w = self.weights.get(sym, 0.0)
            if round(tgt_w, 4) == round(curr_w, 4):
                continue
            if tgt_w == 0.0:
                direction = SignalDirection.CLOSE
            elif tgt_w > curr_w:
                direction = SignalDirection.BUY
            else:
                direction = SignalDirection.SELL

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
