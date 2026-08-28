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


class MacroRotationV4Strategy(BaseStrategy):
    """宏观风控 A+B 终极哑铃策略 (中证红利防守 + 创业板指进攻 + 闲钱固收增强)。

    A (分批与趋势): 结合 Panic/Overheat 极值与 MA20 趋势过滤。
       趋势基准为中证全指 (000985.CSI) 收盘，与宏观管线估值基准保持一致。
    B (哑铃风格轮动): 在恐慌底重仓高弹性成长股(创业板指)，在狂热顶切高股息防守(中证红利)并降仓，破位则空仓。
    C (闲钱生息): 未使用的仓位全自动配置低风险固收资产 (如国债 ETF / 货币基金)。

    输入契约: 按 trade_date 升序的面板，需含 close / panic_index / overheat_index 列，
      其中 close 为中证全指 (000985.CSI) 收盘。
    """

    def __init__(self, context: Context | None = None, ma_window: int = 20) -> None:
        super().__init__(context)
        self.ma_window = ma_window

        # 宽基双核哑铃引擎
        self.sym_defensive = "000922.CSI"  # 中证红利 (防守/高股息托底)
        self.sym_growth = "399006.SZ"  # 创业板指 (进攻/高成长弹性)
        self.benchmark_symbol = "000985.CSI"  # 趋势基准：中证全指

        # 记录当前仓位 (初始默认各 50%)
        self.weights: dict[str, float] = {
            self.sym_defensive: 0.5,
            self.sym_growth: 0.5,
        }

    def on_init(self) -> None:
        """复位跨回测状态，避免多次运行间仓位残留。"""
        self.weights = {
            self.sym_defensive: 0.5,
            self.sym_growth: 0.5,
        }

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新数据，生成多标的轮动交易信号"""
        if data.is_empty() or len(data) < self.ma_window:
            return []
        if not _REQUIRED_COLUMNS.issubset(data.columns):
            logger.warning(
                "MacroRotationV4 数据缺少必需列: %s",
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
        timestamp = _coerce_timestamp(latest.get("trade_date"))

        # 目标仓位字典
        target = self.weights.copy()
        reason = ""

        # ==========================
        # 终极哑铃 A+B 状态机逻辑
        # ==========================
        if overheat > 65 and close < ma20:
            # 【泡沫破裂】右侧跌破：全部清仓 (闲置资金全额转入固收生息)
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 0.0
            reason = f"泡沫破裂逃顶 (Overheat={overheat:.1f}, 跌破MA20)"

        elif overheat > 65 and close >= ma20:
            # 【泡沫膨胀】趋势完好：极度危险但还在涨。
            # 切防守：清仓高危成长股，保留 50% 中证红利防守，其余 50% 转固收
            target[self.sym_defensive] = 0.5
            target[self.sym_growth] = 0.0
            reason = f"泡沫膨胀切防守 (Overheat={overheat:.1f}, 50%中证红利)"

        elif panic > 75:
            # 【极度冰点】流动性崩溃，多杀多。
            # 极限进攻：100% 满仓创业板指，博取核心成长股的极强反弹
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 1.0
            reason = f"极度冰点全仓反击 (Panic={panic:.1f}, 100%创业板指)"

        elif panic > 65:
            # 【恐慌左侧】开始建仓。
            # 均衡偏进攻：50% 创业板指 + 20% 中证红利 + 30% 固收生息
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
