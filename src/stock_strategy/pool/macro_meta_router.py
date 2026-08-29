"""宏观元策略自适应动态路由器 (MacroMetaRouterStrategy)。

根据宏观风控双轨雷达 (Panic / Overheat)、国家队宽基 ETF 托底 (etf_score)、
大盘估值 (dim_valuation) 与 20日均线 (MA20) 趋势，将全市场划分为 5 大宏观相态：
1. 【相态 4：狂热泡沫破裂 (Overheat > 65 & Close < MA20)】-> 100% 刚性清仓空仓避险；
2. 【相态 1：极度恐慌与国家队托底 (Panic > 75 或 Panic > 65 & ETF >= 90)】
   - 左侧探底 (Close < MA20)：配置 50% 沪深300 + 30% 红利 + 20% 创业板 (对齐国家队大盘托底防踩踏)；
   - 右侧突破 (Close >= MA20)：打满 100% 创业板成长 (吃满弹性主升)；
3. 【相态 3：狂热泡沫中继 (Overheat > 65 & Close >= MA20)】-> 50% 红利低波防御锁润；
4. 【相态 2：估值大底与恐慌左侧 (Panic > 65 或 Valuation <= 15%)】-> 40% 红利 + 30% 沪深300 + 30% 创业板 锁仓；
5. 【相态 0：常态趋势自适应】
   - 多头趋势 (Close >= MA20)：60% 创业板 + 40% 红利 (适度成长进攻)；
   - 震荡整理 (Close < MA20)：50% 红利 + 50% 创业板 (标准哑铃平衡)。
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


class MacroMetaRouterStrategy(BaseStrategy):
    """宏观风控元策略自适应动态路由器。"""

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
        valuation_threshold: float = 15.0,
    ) -> None:
        super().__init__(context)
        self.ma_window = ma_window

        # 核心资产池 (默认中证红利、创业板指、沪深300，或对应场内 ETF)
        self.sym_defensive = symbols[0] if symbols and len(symbols) > 0 else "000922.CSI"
        self.sym_growth = symbols[1] if symbols and len(symbols) > 1 else "399006.SZ"
        self.sym_core = symbols[2] if symbols and len(symbols) > 2 else "000300.SH"
        self.benchmark_symbol = benchmark_symbol or "000985.CSI"
        self.panic_threshold = float(panic_threshold)
        self.panic_entry_threshold = float(panic_entry_threshold)
        self.overheat_threshold = float(overheat_threshold)
        self.etf_score_threshold = float(etf_score_threshold)
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
        """复位跨回测状态。"""
        self.weights = dict(self.initial_weights)

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        """根据宏观气象状态机执行全天候动态资产路由。"""
        if data.is_empty() or len(data) < self.ma_window:
            return []
        if not _REQUIRED_COLUMNS.issubset(data.columns):
            logger.warning(
                "MacroMetaRouter 数据缺少必需列: %s",
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

        rep_score_val = latest.get("repurchase_score")
        rep_score = float(rep_score_val) if isinstance(rep_score_val, int | float) else None

        dim_corp_val = latest.get("dim_corporate")
        dim_corp = float(dim_corp_val) if isinstance(dim_corp_val, int | float) else None

        dim_val_raw = latest.get("dim_valuation")
        dim_val = float(dim_val_raw) if isinstance(dim_val_raw, int | float) else None

        timestamp = _coerce_timestamp(latest.get("trade_date"))

        target = self.weights.copy()
        reason = ""

        # 是否触发政策/产业资本强托底共振 (国家队大额申购 ETF 或 企业大额回购潮)
        has_support_resonance = (
            (etf_score is not None and etf_score >= self.etf_score_threshold)
            or (rep_score is not None and rep_score >= 80.0)
            or (dim_corp is not None and dim_corp >= 80.0)
        )

        # ==============================================================
        # 宏观元策略 5 大相态动态路由
        # ==============================================================

        # 相态 4：狂热泡沫破裂逃顶
        if overheat > self.overheat_threshold and close < ma20:
            target[self.sym_defensive] = 0.0
            target[self.sym_growth] = 0.0
            target[self.sym_core] = 0.0
            reason = f"相态4: 泡沫破裂全额清仓 (Overheat={overheat:.1f}, 跌破MA{self.ma_window})"

        # 相态 1：极度恐慌与国家队/产业资本托底抢跑
        elif panic > self.panic_threshold or (
            panic > self.panic_entry_threshold and has_support_resonance
        ):
            if close < ma20:
                # 左侧探底：对齐国家队大盘宽基托底，防微盘踩踏
                target[self.sym_defensive] = 0.3
                target[self.sym_growth] = 0.2
                target[self.sym_core] = 0.5
                etf_desc = f", ETF={etf_score:.1f}" if etf_score is not None else ""
                reason = f"相态1: 政策与产业左侧托底防踩踏 (Panic={panic:.1f}{etf_desc})"
            else:
                # 右侧突破：全仓打满弹性成长
                target[self.sym_defensive] = 0.0
                target[self.sym_growth] = 1.0
                target[self.sym_core] = 0.0
                reason = f"相态1: 恐慌冰点右侧突破全仓反击 (Panic={panic:.1f}, 100%成长)"

        # 相态 3：狂热泡沫膨胀中继锁润
        elif overheat > self.overheat_threshold and close >= ma20:
            target[self.sym_defensive] = 0.5
            target[self.sym_growth] = 0.0
            target[self.sym_core] = 0.0
            reason = f"相态3: 泡沫膨胀中继切红利锁润 (Overheat={overheat:.1f})"

        # 相态 2：估值大底与恐慌左侧建仓
        elif panic > self.panic_entry_threshold or (
            dim_val is not None and dim_val <= self.valuation_threshold
        ):
            target[self.sym_defensive] = 0.4
            target[self.sym_growth] = 0.3
            target[self.sym_core] = 0.3
            reason = f"相态2: 估值/恐慌大底均衡锁仓 (Panic={panic:.1f})"

        # 相态 0：常态中枢区间保持状态机持仓延续 (防止震荡市过度频繁无意义调仓)
        else:
            # 保持当前持仓结构不变
            pass

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
