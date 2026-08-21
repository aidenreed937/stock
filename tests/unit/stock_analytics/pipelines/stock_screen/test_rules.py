"""个股排雷规则测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.stock_screen.rules import (
    evaluate_consecutive_losses,
    evaluate_goodwill_overhang,
    evaluate_holder_selloff,
    evaluate_penny_stock_face_value,
    evaluate_st_marked,
)


def test_st_marked_matches_st_star_st_and_delisting_names() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
            "name": ["正常公司", "ST公司", "*ST公司", "退市整理公司"],
        }
    )

    result = evaluate_st_marked(rows, {"name_regex": r"ST|\*ST|退"})

    assert result.filter(pl.col("status") == "fail")["symbol"].to_list() == [
        "000002.SZ",
        "000003.SZ",
        "000004.SZ",
    ]


def test_penny_stock_boundary_at_two_yuan_passes() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "trade_date": [date(2026, 8, 20), date(2026, 8, 20)],
            "close": [2.0, 1.99],
        }
    )

    result = evaluate_penny_stock_face_value(rows, {"min_close_price": 2.0})

    assert result.filter(pl.col("symbol") == "000001.SZ")["status"].item() == "pass"
    assert result.filter(pl.col("symbol") == "000002.SZ")["status"].item() == "fail"


def test_consecutive_losses_uses_latest_period_in_each_year() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 4,
            "end_date": [
                date(2024, 3, 31),
                date(2024, 12, 31),
                date(2025, 3, 31),
                date(2025, 12, 31),
            ],
            "n_income": [1.0, -2.0, 1.0, -3.0],
        }
    )

    result = evaluate_consecutive_losses(rows, {"loss_years": 2})

    assert result["status"].item() == "fail"


def test_goodwill_threshold_is_strictly_greater_than_fifty_percent() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "ann_date": [date(2026, 6, 30), date(2026, 6, 30)],
            "goodwill": [50.0, 50.1],
            "total_hldr_eqy_exc_min_int": [100.0, 100.0],
        }
    )

    result = evaluate_goodwill_overhang(rows, {"max_goodwill_to_equity": 0.50})

    assert result.filter(pl.col("symbol") == "000001.SZ")["status"].item() == "pass"
    assert result.filter(pl.col("symbol") == "000002.SZ")["status"].item() == "fail"


def test_holder_selloff_uses_de_direction_and_event_dates() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 4,
            "ann_date": [date(2026, 8, 1)] * 4,
            "begin_date": [date(2026, 7, 1), date(2026, 6, 1), date(2026, 5, 1), date(2026, 4, 1)],
            "close_date": [None] * 4,
            "in_de": ["DE", "DE", "IN", "D"],
        }
    )

    result = evaluate_holder_selloff(
        rows,
        {"as_of_date": date(2026, 8, 20), "window_days": 180, "min_sell_count": 2},
    )

    assert result["status"].item() == "warn"
