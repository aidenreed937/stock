from datetime import date

import polars as pl

from stock.analytics.macro.buffett import BuffettIndicatorCalculator, _evaluate_buffett_zone
from stock.analytics.models import ValuationZone


def test_evaluate_buffett_zone() -> None:
    zone, _desc, is_bottom, is_peak = _evaluate_buffett_zone(60.0)
    assert zone == ValuationZone.EXTREME_LOW
    assert is_bottom is True
    assert is_peak is False

    zone, _desc, is_bottom, is_peak = _evaluate_buffett_zone(110.0)
    assert zone == ValuationZone.EXTREME_HIGH
    assert is_bottom is False
    assert is_peak is True


def test_buffett_calculator_series() -> None:
    # 2只股票，total_mv 为元 -> 2026-01-01 总和 8e12 元 = 80000 亿元
    basic_df = pl.DataFrame(
        {
            "trade_date": [
                date(2026, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 2),
            ],
            "symbol": ["000001.SZ", "600519.SH", "000001.SZ", "600519.SH"],
            "total_mv": [3e12, 5e12, 3e12, 5e12],
        }
    )
    # GDP 4 季度 (Q4 为全年累计 100000 亿元)
    gdp_df = pl.DataFrame(
        {
            "quarter": ["2025Q1", "2025Q2", "2025Q3", "2025Q4"],
            "pub_date": [
                date(2025, 4, 15),
                date(2025, 7, 15),
                date(2025, 10, 15),
                date(2026, 1, 1),
            ],
            "gdp": [25000.0, 50000.0, 75000.0, 100000.0],
        }
    )

    calc = BuffettIndicatorCalculator()
    res_df = calc.calculate_series(daily_basic_df=basic_df, gdp_df=gdp_df)

    assert len(res_df) == 2
    # 总市值 80000 亿 / GDP TTM 100000 亿 * 100 = 80.0%
    assert round(res_df["securitization_ratio"][0], 1) == 80.0
