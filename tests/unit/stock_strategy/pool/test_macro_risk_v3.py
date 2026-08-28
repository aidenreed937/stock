from datetime import date

import polars as pl

from stock_strategy.pool.macro_risk_v3 import MacroRiskV3Strategy
from stock_strategy.signal import SignalDirection


def test_macro_risk_v3_panic_extreme() -> None:
    """测试极度恐慌 (Panic > 75) 时全仓买入沪深300"""
    prices = [100.0] * 25
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 3, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [50.0] * 24 + [80.0],
            "overheat_index": [30.0] * 25,
        }
    )

    strategy = MacroRiskV3Strategy()
    strategy.current_weight = 0.0  # 假设之前已空仓
    signals = strategy.on_bar(df)

    assert len(signals) == 1
    assert signals[0].symbol == "000300.SH"
    assert signals[0].target_weight == 1.0
    assert signals[0].direction == SignalDirection.BUY


def test_macro_risk_v3_overheat_broken() -> None:
    """测试泡沫破裂 (Overheat > 65 且跌破 MA20) 时全部清仓"""
    prices = [100.0] * 24 + [80.0]  # 收盘 80 < MA20 (约 99)
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [20.0] * 25,
            "overheat_index": [40.0] * 24 + [70.0],
        }
    )

    strategy = MacroRiskV3Strategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 1
    assert signals[0].symbol == "000300.SH"
    assert signals[0].target_weight == 0.0
    assert signals[0].direction == SignalDirection.CLOSE


def test_macro_risk_v3_insufficient_data() -> None:
    """测试数据不足 MA 周期时不产生信号"""
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1)],
            "close": [100.0],
            "panic_index": [80.0],
            "overheat_index": [20.0],
        }
    )
    strategy = MacroRiskV3Strategy(ma_window=20)
    signals = strategy.on_bar(df)
    assert len(signals) == 0
