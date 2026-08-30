"""MacroRotationV5RebalanceStrategy 单元测试。"""

from datetime import date

import polars as pl

from stock_strategy.pool.macro_rotation_v5_rebalance import MacroRotationV5RebalanceStrategy
from stock_strategy.signal import SignalDirection


def _df(
    prices: list[float], panic: list[float], overheat: list[float], smart: list[float]
) -> pl.DataFrame:
    n = len(prices)
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 3, i + 1) for i in range(n)],
            "close": prices,
            "panic_index": panic,
            "overheat_index": overheat,
            "smart_money_pct": smart,
        }
    )


def test_rebalance_normal_dumbbell_no_signal() -> None:
    """常态 50/50 哑铃缩放后等于初始 35/35/30，不产生信号。"""
    df = _df([100.0] * 25, [45.0] * 25, [45.0] * 25, [50.0] * 25)
    strategy = MacroRotationV5RebalanceStrategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 0


def test_rebalance_extreme_panic_caps_equity_to_70() -> None:
    """极度冰点满仓创业板 → 缩放为 创业板 70% + 固收 30%，红利清仓。"""
    df = _df([100.0] * 25, [50.0] * 24 + [80.0], [30.0] * 25, [60.0] * 25)
    strategy = MacroRotationV5RebalanceStrategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 2
    by_sym = {s.symbol: s for s in signals}
    assert by_sym["510880.SH"].target_weight == 0.0
    assert by_sym["510880.SH"].direction == SignalDirection.CLOSE
    assert by_sym["159915.SZ"].target_weight == 0.7
    assert by_sym["159915.SZ"].direction == SignalDirection.BUY
    assert "权益封顶70%" in by_sym["159915.SZ"].reason


def test_rebalance_overheat_broken_all_fixed() -> None:
    """泡沫破裂逃顶 → 权益归零，固收 100%。"""
    df = _df([100.0] * 24 + [80.0], [20.0] * 25, [40.0] * 24 + [70.0], [10.0] * 25)
    strategy = MacroRotationV5RebalanceStrategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 3
    by_sym = {s.symbol: s for s in signals}
    assert by_sym["510880.SH"].target_weight == 0.0
    assert by_sym["159915.SZ"].target_weight == 0.0
    assert by_sym["511010.SH"].target_weight == 1.0
    assert by_sym["511010.SH"].direction == SignalDirection.BUY


def test_rebalance_panic_left_scaled_to_fixed() -> None:
    """恐慌左侧分批建仓 (红利20+创业板50) → 缩放 红利14 + 创业板35 + 固收51。"""
    df = _df([100.0] * 25, [50.0] * 24 + [68.0], [30.0] * 25, [50.0] * 24 + [60.0])
    strategy = MacroRotationV5RebalanceStrategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 2
    by_sym = {s.symbol: s for s in signals}
    assert abs(by_sym["510880.SH"].target_weight - 0.14) < 1e-6
    assert by_sym["510880.SH"].direction == SignalDirection.SELL
    assert abs(by_sym["511010.SH"].target_weight - 0.51) < 1e-6
    assert by_sym["511010.SH"].direction == SignalDirection.BUY


def test_rebalance_smart_money_filter_no_signal() -> None:
    """恐慌左侧且聪明钱低分位 (<40) → 假黄金坑，不产生任何信号。"""
    df = _df([100.0] * 25, [50.0] * 24 + [68.0], [30.0] * 25, [30.0] * 24 + [25.0])
    strategy = MacroRotationV5RebalanceStrategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 0


def test_rebalance_bias_cut_all_fixed() -> None:
    """极值乖离清仓 → 权益归零，固收 100%。"""
    df = _df([100.0] * 24 + [125.0], [30.0] * 25, [50.0] * 25, [50.0] * 25)
    strategy = MacroRotationV5RebalanceStrategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 3
    by_sym = {s.symbol: s for s in signals}
    assert by_sym["511010.SH"].target_weight == 1.0
    assert "极值乖离清仓避险" in by_sym["511010.SH"].reason
