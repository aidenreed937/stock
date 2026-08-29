"""宏观风控 A+B+C 三核资产与风格动量自适应智能轮动策略 (V6 终极版)。

在 V5 聪明钱增强轮动基础上进行系统性优化升级：
1. 【聪明钱确认与左侧防踩踏】：在恐慌左侧区间 (panic 65~75)，引入聪明钱组合信号
   (smart_money_score < 40) 拦截假黄金坑；若聪明钱确认接货且处于左侧 (Close < MA20)，
   优先配置沪深300压舱石 (40%) 与红利防守 (30%)、创业板 (30%) 防踩踏，企稳后加大成长弹性；
2. 【常态估值与风格自适应】：在常态非极值区间，结合大盘估值分位 (dim_valuation)，
   在极低估值大底战略加配红利与沪深300，避免单边价值牛市踏空；
3. 【极值与均线共振逃顶】：Overheat > 65 时若跌破 MA20 坚决清仓，均线完好时切换红利防守锁润。
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


class MacroRotationV6Strategy(BaseStrategy):
    """宏观风控 V6 三核资产与风格动量自适应智能轮动策略。"""

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
        smart_filter_threshold: float = 40.0,
        valuation_threshold: float = 20.0,
    ) -> None:
        super().__init__(context)
        self.ma_window = ma_window

        # 宽基三核资产引擎 (支持 ETF 代理映射)
        self.sym_defensive = symbols[0] if symbols and len(symbols) > 0 else "000922.CSI"
        self.sym_growth = symbols[1] if symbols and len(symbols) > 1 else "399006.SZ"
        self.sym_core = symbols[2] if symbols and len(symbols) > 2 else "000300.SH"
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.panic_threshold = float(panic_threshold)
        self.panic_entry_threshold = float(panic_entry_threshold)
        self.overheat_threshold = float(overheat_threshold)
        self.smart_filter_threshold = float(smart_filter_threshold)
        self.valuation_threshold = float(valuation_threshold)

        self.initial_weights = (
            dict(initial_weights)
            if initial_weights
            else {
                self.sym_defensive: 0.4,
                self.sym_growth: 0.4,
                self.sym_core: 0.2,
            }
        )
        self.weights = dict(self.initial_weights)

    def on_init(self) -> None:
        """复位跨回测状态，避免多次运行间仓位残留。"""
        self.weights = dict(self.initial_weights)

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新数据，生成三核资产动态轮动交易信号。"""
        if data.is_empty() or len(data) < self.ma_window:
            return []
        if not _REQUIRED_COLUMNS.issubset(data.columns):
            logger.warning(
                "MacroRotationV6 数据缺少必需列: %s",
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

        smart_val = latest.get("smart_money_score")
        smart = float(smart_val) if isinstance(smart_val, int | float) else None

        dim_val_raw = latest.get("dim_valuation")
        dim_val = float(dim_val_raw) if isinstance(dim_val_raw, int | float) else None

        timestamp = _coerce_timestamp(latest.get("trade_date"))

        # 保持当前权重持久化
        target = self.weights.copy()
        reason = ""

        # ==============================================================
        # V6 核心状态机逻辑 (三核驱动 + 聪明钱确认 + 风格自适应)
        # ==============================================================

        # 1. 极端狂热逃顶区
        if overheat > self.overheat_threshold and close < ma20:
            # 泡沫破裂右侧破位：全额清仓转固收
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 0.0
            target[self.sym_core] = 0.0
            reason = f"泡沫破裂逃顶 (Overheat={overheat:.1f}, 跌破MA{self.ma_window})"

        elif overheat > self.overheat_threshold and close >= ma20:
            # 泡沫膨胀但均线完好：切换至 50% 中证红利防守，清空高贝塔成长
            target[self.sym_defensive] = 0.5
            target[self.sym_growth] = 0.0
            target[self.sym_core] = 0.0
            reason = f"泡沫膨胀切红利防守 (Overheat={overheat:.1f})"

        # 2. 极度恐慌冰点区
        elif panic > self.panic_threshold:
            # 极度冰点：100% 满仓高弹性成长股博取反弹
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 1.0
            target[self.sym_core] = 0.0
            reason = f"极度冰点全仓反击 (Panic={panic:.1f}, 100%创业板指)"

        # 3. 恐慌左侧与聪明钱确认区
        elif panic > self.panic_entry_threshold:
            # 聪明钱确认过滤: smart_money_score < 40 判定假黄金坑不建仓
            if smart is not None and smart < self.smart_filter_threshold:
                return []

            if close < ma20:
                # 左侧探底：沪深300压舱防微盘踩踏 (40% 300 + 30% 红利 + 30% 创业板)
                target[self.sym_defensive] = 0.3
                target[self.sym_growth] = 0.3
                target[self.sym_core] = 0.4
                if smart is not None:
                    reason = f"恐慌左侧聪明钱确认建仓 (Panic={panic:.1f}, SmartMoney={smart:.1f})"
                else:
                    reason = f"恐慌左侧分批建仓 (Panic={panic:.1f})"
            else:
                # 右侧企稳：加大成长弹性 (50% 创业板 + 30% 300 + 20% 红利)
                target[self.sym_defensive] = 0.2
                target[self.sym_growth] = 0.5
                target[self.sym_core] = 0.3
                if smart is not None:
                    reason = f"恐慌右侧聪明钱确认进攻 (Panic={panic:.1f}, SmartMoney={smart:.1f})"
                else:
                    reason = f"恐慌右侧企稳进攻 (Panic={panic:.1f})"

        # 4. 常态估值驱动配置（极低估值大底超配价值红利与大盘）
        elif dim_val is not None and dim_val <= self.valuation_threshold:
            target[self.sym_defensive] = 0.5
            target[self.sym_growth] = 0.2
            target[self.sym_core] = 0.3
            reason = f"常态极低估值超配价值红利 (Valuation={dim_val:.1f})"

        # 比较并生成信号
        signals: list[Signal] = []
        for sym, tgt_w in target.items():
            curr_w = self.weights.get(sym, 0.0)
            if tgt_w == curr_w:
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
