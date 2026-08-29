"""宏观风控 A+B 资金博弈多因子智能增强轮动策略 (V5 终极版)。

在 V4 双核哑铃轮动（中证红利防守 + 创业板指进攻 + 闲钱固收增强）基础上，
引入聪明钱组合信号（产业资本增持 + 大宗折价接盘 + 国家队股东锚点等权组合）
作为恐慌左侧的【确认过滤】：
1. 【聪明钱确认过滤】：恐慌左侧区间 (panic 65~75) 若聪明钱信号低分位
   (smart_money_score < 40，内部人/机构/国家队未逆势接货) 判定为假黄金坑，
   不左侧建仓，等待真实资金确认；
2. 【常规极值与均线趋势保护】：保持 V4 优良的双轨制极值确认与 MA20 趋势破位逃顶机制。
3. 【极值乖离止盈】：基准 20 日乖离率 (Bias20) 过大时（如 924 式政策脉冲）清仓避险，
   乖离回落至阈值内即恢复哑铃——与 Overheat+MA20 破位形成"急涨先降仓、破位再清仓"两段式退出。

【钝感持有机制】(分两类，勿混为一谈)：
A. 常态区钝感——V 系列状态机共性，非 V5 特有：状态机仅在极端事件动作
   (Panic>75 / Overheat>65 / 乖离>15%)，震荡阴跌年(如 2023)情绪不过热不恐慌
   时全系列策略均 0 调仓，天然避免反复折腾与摩擦，代价是常态期完全暴露贝塔。
B. 恐慌区过滤——V5 特有：恐慌左侧分支要求 SmartMoney>=40 确认，假黄金坑
   (内部人/机构未逆势接货)不建仓。实证：V5 全周期 314 信号 vs V4 420，
   少掉的 106 次调仓集中于 2018 恐慌反复段(-36 次)，按平均换手 0.3、费率
   0.06% 粗算全周期节省摩擦约 1.9%——主要价值是避免"抄了又砍、砍了又抄"
   的假黄金坑接飞刀，节省摩擦是副产品而非设计目标。
另：恐慌左侧分支目标恒为"红利20%+创业板50%"，与建仓后当前权重一致时，
即使 Panic>65 且聪明钱确认，目标==当前亦不产生信号(如 2022-11-28 建仓后
至 2024-09-30 近两年零调仓，期间靠红利20%+现金30%降波、V 型反转自动吃满反弹)。

注：原"ETF 份额托底提前全仓"分支经四重证据证伪后移除（与国家队真实增持无关、
2024 危机回撤翻倍）；"恐慌区间提前全仓创业板"动作本身经对照回测亦损害风险调整收益，
故以 smart_money_score 做过滤而非激进触发（实证见
data/analytics/macro_strategy/smart_money_composite.md）。
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
        smart_filter_threshold: float = 40.0,
        bias_threshold: float = 0.15,
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
        bias20 = (close / ma20 - 1.0) if ma20 > 0 else 0.0

        smart_val = latest.get("smart_money_score")
        smart = float(smart_val) if isinstance(smart_val, int | float) else None

        timestamp = _coerce_timestamp(latest.get("trade_date"))

        # 目标仓位字典
        target = self.weights.copy()
        reason = ""

        # ==============================================================
        # V5 核心状态机逻辑 (资金博弈智能增强)
        # ==============================================================
        # 0. 极值乖离止盈分支 (优先级最高): 基准 20 日乖离率过大时清仓避险,
        #    规避 924 式政策脉冲后的剧烈均值回归; 乖离回落至阈值内即恢复哑铃。
        #    仅非恐慌区生效 (恐慌区由下方建仓逻辑接管)
        if panic <= self.panic_threshold and bias20 > self.bias_threshold:
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 0.0
            self.bias_cut_active = True
            reason = (
                f"极值乖离清仓避险 (Bias20={bias20:.1%} > {self.bias_threshold:.0%}, "
                f"Panic={panic:.1f})"
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

        elif panic > self.panic_threshold:
            # 3. 极度恐慌冰点：100% 满仓创业板反击
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 1.0
            reason = f"极度冰点全仓反击 (Panic={panic:.1f}, 100%创业板指)"

        elif panic > self.panic_entry_threshold:
            # 4. 恐慌左侧分批建仓：50% 创业板 + 20% 红利
            #    聪明钱确认过滤: smart_money_score < 40 表示内部人/机构/国家队未逆势
            #    接货, 判定假黄金坑不建仓 (等待真实资金确认)
            if smart is not None and smart < self.smart_filter_threshold:
                return []
            target[self.sym_defensive] = 0.2
            target[self.sym_growth] = 0.5
            if smart is not None:
                reason = f"恐慌左侧分批建仓 (Panic={panic:.1f}, SmartMoney={smart:.1f})"
            else:
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
