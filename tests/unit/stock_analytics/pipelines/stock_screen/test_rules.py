"""个股排雷规则测试。"""

from datetime import date

import polars as pl

from stock_analytics.pipelines.stock_screen.rules import (
    evaluate_block_trade_discount,
    evaluate_consecutive_losses,
    evaluate_consecutive_ocf_deficit,
    evaluate_dedt_profit_loss,
    evaluate_goodwill_overhang,
    evaluate_high_leverage_insolvency,
    evaluate_holder_selloff,
    evaluate_lockup_release,
    evaluate_penny_stock_face_value,
    evaluate_pledge_overhang,
    evaluate_receivables_revenue_distortion,
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


def test_dedt_profit_loss_detects_consecutive_negative() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 4,
            "end_date": [
                date(2024, 6, 30),
                date(2024, 12, 31),
                date(2025, 6, 30),
                date(2025, 12, 31),
            ],
            "profit_dedt": [10.0, -5.0, 12.0, -8.0],
        }
    )
    result = evaluate_dedt_profit_loss(rows, {"loss_years": 2})
    assert result["status"].item() == "warn"


def test_lockup_release_identifies_future_window_peak() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "ann_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "float_date": [date(2026, 9, 15), date(2026, 11, 30)],  # 000001 in 60d, 000002 beyond
            "float_ratio": [15.5, 20.0],
        }
    )
    result = evaluate_lockup_release(
        rows,
        {
            "as_of_date": date(2026, 8, 20),
            "forward_days": 60,
            "max_float_ratio": 10.0,
            "universe_symbols": ["000001.SZ", "000002.SZ"],
        },
    )
    assert result.filter(pl.col("symbol") == "000001.SZ")["status"].item() == "warn"
    assert result.filter(pl.col("symbol") == "000002.SZ")["status"].item() == "pass"


def test_pledge_overhang_calculates_unreleased_ratio() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "ann_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "pledge_amount": [600.0, 200.0],
            "holding_amount": [1000.0, 1000.0],
            "is_release": ["0", "0"],
            "release_date": [None, None],
        }
    )
    result = evaluate_pledge_overhang(
        rows,
        {
            "as_of_date": date(2026, 8, 20),
            "max_pledge_ratio": 0.50,
            "universe_symbols": ["000001.SZ", "000002.SZ"],
        },
    )
    assert result.filter(pl.col("symbol") == "000001.SZ")["status"].item() == "warn"
    assert result.filter(pl.col("symbol") == "000002.SZ")["status"].item() == "pass"


def test_high_leverage_insolvency_detects_high_debt_and_low_cr() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "ann_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "debt_to_assets": [88.0, 70.0],
            "current_ratio": [0.6, 1.5],
        }
    )
    result = evaluate_high_leverage_insolvency(
        rows,
        {"max_debt_to_assets": 85.0, "min_current_ratio": 0.8},
    )
    assert result.filter(pl.col("symbol") == "000001.SZ")["status"].item() == "warn"
    assert result.filter(pl.col("symbol") == "000002.SZ")["status"].item() == "pass"


def test_receivables_revenue_distortion_triggers_above_threshold() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "ann_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "accounts_receiv": [90.0, 30.0],
            "revenue": [100.0, 100.0],
        }
    )
    result = evaluate_receivables_revenue_distortion(
        rows,
        {"max_receivables_ratio": 0.80},
    )
    assert result.filter(pl.col("symbol") == "000001.SZ")["status"].item() == "warn"
    assert result.filter(pl.col("symbol") == "000002.SZ")["status"].item() == "pass"


def test_block_trade_discount_triggers_on_large_amounts() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "trade_date": [date(2026, 8, 10), date(2026, 7, 1)],  # 000002 is outside 30d
            "amount": [30_000_000.0, 50_000_000.0],
        }
    )
    result = evaluate_block_trade_discount(
        rows,
        {
            "as_of_date": date(2026, 8, 20),
            "window_days": 30,
            "min_total_amount": 20_000_000.0,
            "universe_symbols": ["000001.SZ", "000002.SZ"],
        },
    )
    assert result.filter(pl.col("symbol") == "000001.SZ")["status"].item() == "warn"
    assert result.filter(pl.col("symbol") == "000002.SZ")["status"].item() == "pass"


def test_consecutive_ocf_deficit_detects_all_negative_cashflow() -> None:
    rows = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 4,
            "end_date": [
                date(2024, 6, 30),
                date(2024, 12, 31),
                date(2025, 6, 30),
                date(2025, 12, 31),
            ],
            "n_cashflow_act": [10.0, -50.0, 20.0, -80.0],
        }
    )
    result = evaluate_consecutive_ocf_deficit(rows, {"loss_years": 2})
    assert result["status"].item() == "warn"
