"""MacroRotationV5Strategy 单元测试。"""

from datetime import date

import polars as pl

from stock_strategy.pool.macro_rotation_v5 import MacroRotationV5Strategy
from stock_strategy.signal import SignalDirection


def test_macro_rotation_v5_smart_money_filter_blocks_fake_bottom() -> None:
    """测试恐慌左侧且聪明钱低分位 (<40) 时判定假黄金坑，不左侧建仓"""
    prices = [100.0] * 25
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 3, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [50.0] * 24 + [68.0],  # 处于 65~75 恐慌区
            "overheat_index": [30.0] * 25,
            "smart_money_score": [30.0] * 24 + [25.0],  # 聪明钱未逆势接货
        }
    )

    strategy = MacroRotationV5Strategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 0


def test_macro_rotation_v5_smart_money_confirmed_build() -> None:
    """测试恐慌左侧且聪明钱确认 (>=40) 时正常左侧建仓 50/20"""
    prices = [100.0] * 25
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 3, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [50.0] * 24 + [68.0],
            "overheat_index": [30.0] * 25,
            "smart_money_score": [50.0] * 24 + [60.0],  # 聪明钱活跃
        }
    )

    strategy = MacroRotationV5Strategy()
    signals = strategy.on_bar(df)

    # 初始 50/50 -> 目标 20/50: 仅防守仓减仓 (成长仓不变不产生信号)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.symbol == "000922.CSI"
    assert sig.target_weight == 0.2
    assert sig.direction == SignalDirection.SELL
    assert "恐慌左侧分批建仓" in sig.reason


def test_macro_rotation_v5_overheat_broken() -> None:
    """测试泡沫破裂 (Overheat > 65 且跌破 MA20) 时全部清仓转固收"""
    prices = [100.0] * 24 + [80.0]  # 收盘跌破均线
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [20.0] * 25,
            "overheat_index": [40.0] * 24 + [70.0],
            "smart_money_score": [10.0] * 25,
        }
    )

    strategy = MacroRotationV5Strategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 2
    for s in signals:
        assert s.target_weight == 0.0
        assert s.direction == SignalDirection.CLOSE
        assert "泡沫破裂逃顶" in s.reason


def test_macro_rotation_v5_normal_fallback() -> None:
    """测试常态阶段保持 50/50 哑铃配置"""
    prices = [100.0] * 25
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [45.0] * 25,
            "overheat_index": [45.0] * 25,
            "smart_money_score": [50.0] * 25,
        }
    )
    strategy = MacroRotationV5Strategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 0
