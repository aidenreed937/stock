"""MacroRotationV5Strategy 单元测试。"""

from datetime import date

import polars as pl

from stock_strategy.pool.macro_rotation_v5 import MacroRotationV5Strategy
from stock_strategy.signal import SignalDirection


def test_macro_rotation_v5_national_team_support() -> None:
    """测试恐慌左侧国家队大额托底 (panic > 65 且 etf_score >= 90) 时提前全仓买入创业板指"""
    prices = [100.0] * 25
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 3, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [50.0] * 24 + [68.0],  # 处于 65~75 恐慌区
            "overheat_index": [30.0] * 25,
            "etf_flow_ratio_score": [20.0] * 24 + [95.0],  # 国家队狂买
            "divergence_score_score": [30.0] * 25,
        }
    )

    strategy = MacroRotationV5Strategy()
    signals = strategy.on_bar(df)

    assert len(signals) == 2
    sym_map = {s.symbol: s for s in signals}
    assert sym_map["000922.CSI"].target_weight == 0.0
    assert sym_map["000922.CSI"].direction == SignalDirection.CLOSE
    assert sym_map["399006.SZ"].target_weight == 1.0
    assert sym_map["399006.SZ"].direction == SignalDirection.BUY
    assert "国家队托底" in sym_map["399006.SZ"].reason


def test_macro_rotation_v5_overheat_broken() -> None:
    """测试泡沫破裂 (Overheat > 65 且跌破 MA20) 时全部清仓转固收"""
    prices = [100.0] * 24 + [80.0]  # 收盘跌破均线
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(25)],
            "close": prices,
            "panic_index": [20.0] * 25,
            "overheat_index": [40.0] * 24 + [70.0],
            "etf_flow_ratio_score": [10.0] * 25,
            "divergence_score_score": [20.0] * 25,
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
            "etf_flow_ratio_score": [50.0] * 25,
            "divergence_score_score": [50.0] * 25,
        }
    )
    strategy = MacroRotationV5Strategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 0
