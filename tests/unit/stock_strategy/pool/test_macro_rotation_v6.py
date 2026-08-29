from datetime import date

import polars as pl

from stock_strategy.pool.macro_rotation_v6 import MacroRotationV6Strategy


def _panel(
    *,
    close_last: float = 100.0,
    panic_last: float = 20.0,
    overheat_last: float = 40.0,
    smart_score_last: float | None = 50.0,
    dim_val_last: float | None = 50.0,
) -> pl.DataFrame:
    n = 25
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(n)],
            "close": [100.0] * (n - 1) + [close_last],
            "panic_index": [20.0] * (n - 1) + [panic_last],
            "overheat_index": [40.0] * (n - 1) + [overheat_last],
            "smart_money_score": [50.0] * (n - 1) + [smart_score_last],
            "dim_valuation": [50.0] * (n - 1) + [dim_val_last],
        }
    )


def test_v6_missing_columns_returns_empty() -> None:
    df = pl.DataFrame({"trade_date": [date(2026, 1, 1)], "close": [100.0]})
    assert MacroRotationV6Strategy().on_bar(df) == []


def test_v6_on_init_resets_weights() -> None:
    strategy = MacroRotationV6Strategy()
    strategy.weights = {"000922.CSI": 0.0, "399006.SZ": 0.0, "000300.SH": 0.0}
    strategy.on_init()
    assert strategy.weights == {
        "000922.CSI": 0.4,
        "399006.SZ": 0.4,
        "000300.SH": 0.2,
    }


def test_v6_overheat_break_ma20_clears_positions() -> None:
    # 跌破 MA20 且 Overheat > 65 -> 清仓
    df = _panel(close_last=80.0, overheat_last=70.0)
    strategy = MacroRotationV6Strategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 3
    for sig in signals:
        assert sig.target_weight == 0.0
        assert sig.direction.name == "CLOSE"


def test_v6_overheat_holding_ma20_cuts_to_defensive() -> None:
    # Overheat > 65 且 close >= MA20 -> 50% 红利防守
    df = _panel(close_last=105.0, overheat_last=70.0)
    strategy = MacroRotationV6Strategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 3
    sig_map = {s.symbol: s.target_weight for s in signals}
    assert sig_map["000922.CSI"] == 0.5
    assert sig_map["399006.SZ"] == 0.0
    assert sig_map["000300.SH"] == 0.0


def test_v6_extreme_panic_goes_all_in_growth() -> None:
    # Panic > 75 -> 100% 创业板
    df = _panel(panic_last=80.0)
    strategy = MacroRotationV6Strategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 3
    sig_map = {s.symbol: s.target_weight for s in signals}
    assert sig_map["399006.SZ"] == 1.0
    assert sig_map["000922.CSI"] == 0.0
    assert sig_map["000300.SH"] == 0.0


def test_v6_smart_filter_blocks_false_dip() -> None:
    # Panic 65~75 但 smart_money_score < 40 -> 判定假黄金坑，不建仓
    df = _panel(close_last=80.0, panic_last=68.0, smart_score_last=30.0)
    strategy = MacroRotationV6Strategy()
    signals = strategy.on_bar(df)
    assert signals == []


def test_v6_smart_confirmed_left_side_allocates_core_index() -> None:
    # Panic 65~75, smart_money_score >= 40, close < MA20 (左侧探底) -> 40% 沪深300 + 30% 红利 + 30% 创业板
    df = _panel(close_last=80.0, panic_last=68.0, smart_score_last=60.0)
    strategy = MacroRotationV6Strategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 3
    sig_map = {s.symbol: s.target_weight for s in signals}
    assert sig_map["000300.SH"] == 0.4
    assert sig_map["000922.CSI"] == 0.3
    assert sig_map["399006.SZ"] == 0.3


def test_v6_smart_confirmed_right_side_increases_growth() -> None:
    # Panic 65~75, smart_money_score >= 40, close >= MA20 (右侧企稳) -> 50% 创业板 + 30% 300 + 20% 红利
    df = _panel(close_last=105.0, panic_last=68.0, smart_score_last=60.0)
    strategy = MacroRotationV6Strategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 3
    sig_map = {s.symbol: s.target_weight for s in signals}
    assert sig_map["399006.SZ"] == 0.5
    assert sig_map["000300.SH"] == 0.3
    assert sig_map["000922.CSI"] == 0.2


def test_v6_low_valuation_regime_allocates_value_defense() -> None:
    # 常态区间且 dim_val <= 20 -> 50% 红利 + 30% 沪深300 + 20% 创业板
    df = _panel(dim_val_last=15.0)
    strategy = MacroRotationV6Strategy()
    signals = strategy.on_bar(df)
    assert len(signals) == 3
    sig_map = {s.symbol: s.target_weight for s in signals}
    assert sig_map["000922.CSI"] == 0.5
    assert sig_map["000300.SH"] == 0.3
    assert sig_map["399006.SZ"] == 0.2
