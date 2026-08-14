from datetime import date

import polars as pl

from stock.analytics.macro.ey_by import EYBYCalculator, _evaluate_eyby_zone
from stock.analytics.models import ValuationZone


def test_evaluate_eyby_zone() -> None:
    zone, _desc, is_bottom, is_peak = _evaluate_eyby_zone(2.5)
    assert zone == ValuationZone.EXTREME_LOW
    assert is_bottom is True
    assert is_peak is False

    zone, _desc, is_bottom, is_peak = _evaluate_eyby_zone(1.0)
    assert zone == ValuationZone.EXTREME_HIGH
    assert is_bottom is False
    assert is_peak is True

    zone, _desc, is_bottom, is_peak = _evaluate_eyby_zone(1.5)
    assert zone == ValuationZone.FAIR
    assert is_bottom is False
    assert is_peak is False


def test_eyby_calculator_series() -> None:
    idx_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "symbol": ["000300", "000300"],
            "pe_ttm.mcw": [20.0, 10.0],
        }
    )
    bond_df = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "ten_y": [2.5, 2.0],
        }
    )

    calc = EYBYCalculator()
    res_df = calc.calculate_series(symbol="000300", index_df=idx_df, bond_df=bond_df)

    assert len(res_df) == 2
    # 2026-01-01: EY = 100 / 20 = 5.0%, BY = 2.5%, EY/BY = 2.0x
    assert res_df["ey_by_ratio"][0] == 2.0
    # 2026-01-02: EY = 100 / 10 = 10.0%, BY = 2.0%, EY/BY = 5.0x
    assert res_df["ey_by_ratio"][1] == 5.0


def test_eyby_calculator_empty_handling() -> None:
    calc = EYBYCalculator()
    assert calc.calculate_series(symbol="000300", index_df=pl.DataFrame()).is_empty()
    assert calc.calculate_latest(symbol="INVALID_CODE") is None
