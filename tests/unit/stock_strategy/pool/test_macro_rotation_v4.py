from datetime import date

import polars as pl

from stock_strategy.pool.macro_rotation_v4 import MacroRotationV4Strategy
from stock_strategy.signal import SignalDirection


def test_macro_rotation_v4_panic_extreme() -> None:
    """测试极度恐慌 (Panic > 75) 时全仓买入创业板指，清仓中证红利"""
    prices = [100.0] * 25
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 3, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [50.0] * 24 + [80.0],
            "overheat_index": [30.0] * 25,
        }
    )

    strategy = MacroRotationV4Strategy()
    signals = strategy.on_bar(df)

    # 应该有两个信号：清仓中证红利 (0.0)，满仓创业板指 (1.0)
    assert len(signals) == 2
    sym_map = {s.symbol: s for s in signals}
    assert sym_map["000922.CSI"].target_weight == 0.0
    assert sym_map["000922.CSI"].direction == SignalDirection.CLOSE
    assert sym_map["399006.SZ"].target_weight == 1.0
    assert sym_map["399006.SZ"].direction == SignalDirection.BUY


def test_macro_rotation_v4_overheat_broken() -> None:
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

    strategy = MacroRotationV4Strategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 2
    for s in signals:
        assert s.target_weight == 0.0
        assert s.direction == SignalDirection.CLOSE


def test_macro_rotation_v4_insufficient_data() -> None:
    """测试数据不足 MA 周期时不产生信号"""
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1)],
            "close": [100.0],
            "panic_index": [80.0],
            "overheat_index": [20.0],
        }
    )
    strategy = MacroRotationV4Strategy(ma_window=20)
    signals = strategy.on_bar(df)
    assert len(signals) == 0
