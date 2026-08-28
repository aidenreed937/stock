from datetime import date

import polars as pl

from stock_strategy.pool.macro_risk_v3 import MacroRiskV3Strategy
from stock_strategy.pool.macro_rotation_v4 import MacroRotationV4Strategy


def _panel(*, close_last: float = 100.0, overheat_last: float = 40.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(25)],
            "close": [100.0] * 24 + [close_last],
            "panic_index": [20.0] * 25,
            "overheat_index": [40.0] * 24 + [overheat_last],
        }
    )


def test_v3_missing_columns_returns_empty() -> None:
    df = pl.DataFrame({"trade_date": [date(2026, 1, 1)], "close": [100.0]})
    assert MacroRiskV3Strategy().on_bar(df) == []


def test_v4_missing_columns_returns_empty() -> None:
    df = pl.DataFrame({"trade_date": [date(2026, 1, 1)], "close": [100.0]})
    assert MacroRotationV4Strategy().on_bar(df) == []


def test_v3_handles_unsorted_input() -> None:
    df = _panel(close_last=80.0, overheat_last=70.0)
    # 把最新一行移到最前，制造乱序
    df = df.gather(pl.Series([24] + list(range(24))))
    signals = MacroRiskV3Strategy().on_bar(df)
    assert len(signals) == 1
    assert signals[0].target_weight == 0.0
    assert signals[0].direction.name == "CLOSE"


def test_v3_none_factor_returns_empty() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 6, i + 1) for i in range(25)],
            "close": [100.0] * 25,
            "panic_index": [50.0] * 24 + [None],
            "overheat_index": [30.0] * 25,
        }
    )
    assert MacroRiskV3Strategy().on_bar(df) == []


def test_v3_string_trade_date_coerced_to_date() -> None:
    df = pl.DataFrame(
        {
            "trade_date": ["2026-06-01"] * 25,
            "close": [100.0] * 25,
            "panic_index": [80.0] * 25,
            "overheat_index": [30.0] * 25,
        }
    )
    strategy = MacroRiskV3Strategy()
    strategy.current_weight = 0.0
    signals = strategy.on_bar(df)
    assert len(signals) == 1
    assert signals[0].timestamp == date(2026, 6, 1)
    assert signals[0].target_weight == 1.0


def test_v4_benchmark_symbol_is_csi985() -> None:
    strategy = MacroRotationV4Strategy()
    assert strategy.benchmark_symbol == "000985.CSI"
    assert set(strategy.weights) == {"000922.CSI", "399006.SZ"}


def test_v4_on_init_resets_weights() -> None:
    strategy = MacroRotationV4Strategy()
    strategy.weights = {"000922.CSI": 0.0, "399006.SZ": 0.0}
    strategy.on_init()
    assert strategy.weights == {"000922.CSI": 0.5, "399006.SZ": 0.5}
