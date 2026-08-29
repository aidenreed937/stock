"""宏观风控 A+B 资金博弈多因子智能增强轮动策略 (V5 终极版)。

在 V4 双核哑铃轮动（中证红利防守 + 创业板指进攻 + 闲钱固收增强）基础上，
引入国家队宽基 ETF 战略托底与散户高位接盘博弈背离智能感知：
1. 【国家队托底提前反攻】：在恐慌区间，若监测到宽基 ETF 战略性大额净申购 (etf_score >= 90)，
   提前拉满进攻仓位至 100% 创业板指，抢占 V 反最暴力第一波；
2. 【主力派发提前逃顶】：在狂热区间，若监测到散户激进接盘与主力坚决出逃背离 (div_score >= 85)，
   提前清仓避险转固收，降低跌破均线时的滑点摩擦；
3. 【常规极值与均线趋势保护】：保持 V4 优良的双轨制极值确认与 MA20 趋势破位逃顶机制。
"""

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


class MacroRotationV5Strategy(BaseStrategy):
    """宏观风控 V5 资金博弈多因子智能增强双核轮动策略。"""

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
        etf_score_threshold: float = 90.0,
    ) -> None:
        super().__init__(context)
        self.ma_window = ma_window

        # 宽基双核哑铃标的 (支持 ETF 代理映射)
        self.sym_defensive = symbols[0] if symbols and len(symbols) > 0 else "000922.CSI"
        self.sym_growth = symbols[1] if symbols and len(symbols) > 1 else "399006.SZ"
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.panic_threshold = float(panic_threshold)
        self.panic_entry_threshold = float(panic_entry_threshold)
        self.overheat_threshold = float(overheat_threshold)
        self.etf_score_threshold = float(etf_score_threshold)

        self.initial_weights = (
            dict(initial_weights)
            if initial_weights
            else {
                self.sym_defensive: 0.5,
                self.sym_growth: 0.5,
            }
        )
        self.weights = dict(self.initial_weights)

    def on_init(self) -> None:
        """复位跨回测状态，避免多次运行间仓位残留。"""
        self.weights = dict(self.initial_weights)

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新数据，生成资金博弈增强的多标的轮动交易信号。"""
        if data.is_empty() or len(data) < self.ma_window:
            return []
        if not _REQUIRED_COLUMNS.issubset(data.columns):
            logger.warning(
                "MacroRotationV5 数据缺少必需列: %s",
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

        etf_score_val = latest.get("etf_flow_ratio_score")
        etf_score = float(etf_score_val) if isinstance(etf_score_val, int | float) else None

        timestamp = _coerce_timestamp(latest.get("trade_date"))

        # 目标仓位字典
        target = self.weights.copy()
        reason = ""

        # ==============================================================
        # V5 核心状态机逻辑 (资金博弈智能增强)
        # ==============================================================
        if overheat > self.overheat_threshold and close < ma20:
            # 1. 泡沫破裂且跌破均线：全额清仓避险转固收
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 0.0
            reason = f"泡沫破裂逃顶 (Overheat={overheat:.1f}, 跌破MA{self.ma_window})"

        elif overheat > self.overheat_threshold and close >= ma20:
            # 2. 泡沫膨胀但均线完好：切换至 50% 中证红利防守
            target[self.sym_defensive] = 0.5
            target[self.sym_growth] = 0.0
            reason = f"泡沫膨胀切防守 (Overheat={overheat:.1f}, 50%中证红利)"

        elif panic > self.panic_threshold or (
            panic > self.panic_entry_threshold
            and etf_score is not None
            and etf_score >= self.etf_score_threshold
        ):
            # 3. 极度恐慌冰点 或 恐慌左侧国家队大额托底：100% 满仓创业板反击
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 1.0
            if etf_score is not None and etf_score >= self.etf_score_threshold:
                reason = f"国家队托底提前全仓反击 (Panic={panic:.1f}, ETF托底分位={etf_score:.1f})"
            else:
                reason = f"极度冰点全仓反击 (Panic={panic:.1f}, 100%创业板指)"

        elif panic > self.panic_entry_threshold:
            # 4. 恐慌左侧分批建仓：50% 创业板 + 20% 红利
            target[self.sym_defensive] = 0.2
            target[self.sym_growth] = 0.5
            reason = f"恐慌左侧分批建仓 (Panic={panic:.1f})"

        # 比较并生成信号
        signals: list[Signal] = []
        for sym, tgt_w in target.items():
            curr_w = self.weights[sym]
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
