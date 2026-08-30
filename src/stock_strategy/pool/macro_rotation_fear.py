"""宏观风控「恐惧前置抄底」双核哑铃轮动策略 (V5-fear 变体)。

在 V5 资金博弈多因子智能增强轮动策略基础上，将恐慌左侧的抄底触发信号从
综合恐慌指数 ``panic_index`` 替换为恐慌情绪维度 ``dim_fear`` (pcr/iv/vix 三因子均值)：

1. 【恐惧前置抄底】：``dim_fear`` 为纯粹的恐慌情绪维度，在熊市谷底前 5~10 日即冲高，
   较 ``panic_index`` (混入广度/资金流等同步滞后确认) 更早更准。全样本复算：
   ``dim_fear > 80`` 后 60 日胜率 74.1% / 均收益 +7.23%，优于 ``panic_index > 75``
   的 69.0% / +6.57%，且样本更多 (255 vs 119)。
2. 【逃顶逻辑不变】：沿用 V5 的 Overheat+MA20 破位逃顶与极值乖离止盈机制。
3. 【聪明钱确认过滤不变】：恐慌左侧 (fear 65~80) 仍以 smart_money_pct 过滤假黄金坑。

与 V5 的唯一差异是抄底触发信号源 (fear 替代 panic)，其余状态机、摩擦、标的均保持一致，
用于干净的 A/B 对照。实证见 data/analytics/macro_strategy/smart_money_composite.md。
"""

from datetime import date, datetime

import polars as pl

from stock_core.utils.logger import logger
from stock_strategy.base import BaseStrategy
from stock_strategy.context import Context
from stock_strategy.signal import Signal, SignalDirection

_REQUIRED_COLUMNS = frozenset({"trade_date", "close", "dim_fear", "overheat_index"})


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


class MacroRotationFearStrategy(BaseStrategy):
    """宏观风控恐惧前置抄底双核哑铃轮动策略。"""

    def __init__(
        self,
        context: Context | None = None,
        ma_window: int = 20,
        symbols: tuple[str, ...] | list[str] | None = None,
        initial_weights: dict[str, float] | None = None,
        benchmark_symbol: str | None = None,
        fear_threshold: float = 80.0,
        fear_entry_threshold: float = 65.0,
        overheat_threshold: float = 65.0,
        smart_filter_threshold: float = 40.0,
        bias_threshold: float = 0.15,
    ) -> None:
        super().__init__(context)
        self.ma_window = ma_window

        # 宽基双核哑铃标的 (支持 ETF 代理映射)
        self.sym_defensive = symbols[0] if symbols and len(symbols) > 0 else "000922.CSI"
        self.sym_growth = symbols[1] if symbols and len(symbols) > 1 else "399006.SZ"
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.fear_threshold = float(fear_threshold)
        self.fear_entry_threshold = float(fear_entry_threshold)
        self.overheat_threshold = float(overheat_threshold)
        self.smart_filter_threshold = float(smart_filter_threshold)
        # 极值乖离止盈阈值: 基准 20 日乖离率 (close/MA20 - 1) 超过该值且非恐慌区时清仓
        self.bias_threshold = float(bias_threshold)
        self.bias_cut_active = False

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
        self.bias_cut_active = False

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """处理最新数据，生成恐惧前置抄底的多标的轮动交易信号。"""
        if data.is_empty() or len(data) < self.ma_window:
            return []
        if not _REQUIRED_COLUMNS.issubset(data.columns):
            logger.warning(
                "MacroRotationFear 数据缺少必需列: %s",
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
        fear_val = latest.get("dim_fear")
        overheat_val = latest.get("overheat_index")
        if close_val is None or fear_val is None or overheat_val is None:
            return []
        close = float(close_val)
        fear = float(fear_val)
        overheat = float(overheat_val)
        bias20 = (close / ma20 - 1.0) if ma20 > 0 else 0.0

        smart_val = latest.get("smart_money_pct")
        smart = float(smart_val) if isinstance(smart_val, int | float) else None

        timestamp = _coerce_timestamp(latest.get("trade_date"))

        # 目标仓位字典
        target = self.weights.copy()
        reason = ""

        # ==============================================================
        # 恐惧前置抄底状态机逻辑
        # ==============================================================
        # 0. 极值乖离止盈分支 (优先级最高): 基准 20 日乖离率过大时清仓避险,
        #    仅非恐慌区生效 (恐慌区由下方建仓逻辑接管)
        if fear <= self.fear_threshold and bias20 > self.bias_threshold:
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 0.0
            self.bias_cut_active = True
            reason = (
                f"极值乖离清仓避险 (Bias20={bias20:.1%} > {self.bias_threshold:.0%}, "
                f"Fear={fear:.1f})"
            )

        elif self.bias_cut_active and bias20 <= self.bias_threshold:
            # 乖离回落至阈值内: 恢复初始哑铃配置
            self.bias_cut_active = False
            target = dict(self.initial_weights)
            reason = f"极值乖离回落恢复哑铃 (Bias20={bias20:.1%})"

        elif overheat > self.overheat_threshold and close < ma20:
            # 1. 泡沫破裂且跌破均线：全额清仓避险转固收
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 0.0
            reason = f"泡沫破裂逃顶 (Overheat={overheat:.1f}, 跌破MA{self.ma_window})"

        elif overheat > self.overheat_threshold and close >= ma20:
            # 2. 泡沫膨胀但均线完好：切换至 50% 中证红利防守
            target[self.sym_defensive] = 0.5
            target[self.sym_growth] = 0.0
            reason = f"泡沫膨胀切防守 (Overheat={overheat:.1f}, 50%中证红利)"

        elif fear > self.fear_threshold:
            # 3. 极度恐慌冰点 (恐惧前置): 100% 满仓创业板反击
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 1.0
            reason = f"恐惧前置全仓反击 (Fear={fear:.1f}, 100%创业板指)"

        elif fear > self.fear_entry_threshold:
            # 4. 恐慌左侧分批建仓：50% 创业板 + 20% 红利
            #    聪明钱确认过滤: smart_money_pct < 40 表示内部人/机构/国家队未逆势
            #    接货, 判定假黄金坑不建仓 (等待真实资金确认)
            if smart is not None and smart < self.smart_filter_threshold:
                return []
            target[self.sym_defensive] = 0.2
            target[self.sym_growth] = 0.5
            if smart is not None:
                reason = f"恐惧前置分批建仓 (Fear={fear:.1f}, SmartMoney={smart:.1f})"
            else:
                reason = f"恐惧前置分批建仓 (Fear={fear:.1f})"

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
