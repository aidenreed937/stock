"""可转债领域 Mart 测试。"""

from datetime import date

import polars as pl

from stock_analytics.marts.convertible_bond import build_convertible_bond_mart


def test_build_convertible_bond_mart_aggregates_daily_cross_section() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": ["2026-08-02", "2026-08-01", "2026-08-01"],
            "close": [100.0, 105.0, 120.0],
            "cb_over_rate": [8.0, 10.0, 20.0],
            "bond_over_rate": [2.0, 4.0, 6.0],
        }
    )

    result = build_convertible_bond_mart(frame)

    assert result["trade_date"].to_list() == [date(2026, 8, 1), date(2026, 8, 2)]
    first_day = result.row(0, named=True)
    assert first_day["cb_price_median"] == 112.5
    assert first_day["cb_conversion_premium_median"] == 15.0
    assert first_day["cb_bond_premium_median"] == 5.0
    assert first_day["cb_valid_count"] == 2
    assert first_day["cb_low_price_count"] == 1
    assert first_day["cb_below_par_count"] == 0

    second_day = result.row(1, named=True)
    assert second_day["cb_below_par_count"] == 1


def test_build_convertible_bond_mart_empty_has_stable_schema() -> None:
    result = build_convertible_bond_mart(pl.DataFrame())

    assert result.is_empty()
    assert result.columns == [
        "trade_date",
        "cb_price_median",
        "cb_conversion_premium_median",
        "cb_bond_premium_median",
        "cb_valid_count",
        "cb_low_price_count",
        "cb_below_par_count",
    ]
