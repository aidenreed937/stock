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
            "smart_money_pct": [30.0] * 24 + [25.0],  # 聪明钱未逆势接货
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
            "smart_money_pct": [50.0] * 24 + [60.0],  # 聪明钱活跃
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
            "smart_money_pct": [10.0] * 25,
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
            "smart_money_pct": [50.0] * 25,
        }
    )
    strategy = MacroRotationV5Strategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 0


def test_macro_rotation_v5_bias_cut_clears_on_extreme_deviation() -> None:
    """极值乖离止盈: 基准 20 日乖离率 > 15% 且非恐慌区时清仓避险 (924 式脉冲)。"""
    # 前 24 天横盘 100，最后一天跳涨至 125 (Bias20 ≈ 25%)
    prices = [100.0] * 24 + [125.0]
    df = pl.DataFrame(
        {
            "trade_date": [date(2024, 9, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [30.0] * 25,  # 非恐慌区
            "overheat_index": [50.0] * 25,
            "smart_money_pct": [50.0] * 25,
        }
    )
    strategy = MacroRotationV5Strategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 2
    for s in signals:
        assert s.target_weight == 0.0
        assert s.direction == SignalDirection.CLOSE
        assert "极值乖离清仓避险" in s.reason
    assert strategy.bias_cut_active is True


def test_macro_rotation_v5_bias_recover_restores_dumbbell() -> None:
    """乖离回落至阈值内后恢复初始哑铃 50/50。"""
    # 先触发清仓: 最后一天跳涨 25%
    prices1 = [100.0] * 24 + [125.0]
    df1 = pl.DataFrame(
        {
            "trade_date": [date(2024, 9, i + 1) for i in range(25)],
            "close": prices1,
            "panic_index": [30.0] * 25,
            "overheat_index": [50.0] * 25,
            "smart_money_pct": [50.0] * 25,
        }
    )
    strategy = MacroRotationV5Strategy()
    strategy.on_bar(df1)
    assert strategy.bias_cut_active is True

    # 次日价格回落至 100 (Bias20 回到 0)，应恢复哑铃
    prices2 = [100.0] * 24 + [125.0, 100.0]
    df2 = pl.DataFrame(
        {
            "trade_date": [date(2024, 9, i + 1) for i in range(26)],
            "close": prices2,
            "panic_index": [30.0] * 26,
            "overheat_index": [50.0] * 26,
            "smart_money_pct": [50.0] * 26,
        }
    )
    signals = strategy.on_bar(df2)

    assert strategy.bias_cut_active is False
    # 应从 0/0 恢复为 50/50: 两个标的都产生 BUY 信号
    assert len(signals) == 2
    for s in signals:
        assert s.target_weight == 0.5
        assert s.direction == SignalDirection.BUY
        assert "极值乖离回落恢复哑铃" in s.reason


def test_macro_rotation_v5_bias_cut_skipped_in_panic() -> None:
    """恐慌区 (Panic > 阈值) 时乖离止盈不触发，交给建仓逻辑接管。"""
    prices = [100.0] * 24 + [125.0]  # Bias20 高企
    df = pl.DataFrame(
        {
            "trade_date": [date(2024, 2, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [80.0] * 25,  # 极度恐慌
            "overheat_index": [30.0] * 25,
            "smart_money_pct": [60.0] * 25,
        }
    )
    strategy = MacroRotationV5Strategy()
    signals = strategy.on_bar(df)

    # 恐慌区应触发极度冰点全仓反击，而非乖离清仓
    assert signals
    assert all("极值乖离" not in s.reason for s in signals)
    assert strategy.bias_cut_active is False
