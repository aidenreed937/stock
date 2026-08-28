from datetime import date

import polars as pl
import pytest

from stock_strategy.macro_report import compute_stats, nav_from_close


def test_nav_from_close_normalizes_first_day() -> None:
    close = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
            "close": [100.0, 110.0, 121.0],
        }
    )
    nav = nav_from_close(close)
    assert nav["trade_date"].to_list() == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    assert nav["nav"].to_list() == [1.0, 1.1, 1.21]


def test_nav_from_close_truncates_window() -> None:
    close = pl.DataFrame(
        {
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
            "close": [100.0, 110.0, 121.0],
        }
    )
    nav = nav_from_close(close, start_date=date(2026, 1, 2), end_date=date(2026, 1, 3))
    assert nav["nav"].to_list() == pytest.approx([1.0, 1.1])


def test_compute_stats_basic_metrics() -> None:
    nav = pl.DataFrame({"nav": [1.0, 1.2, 0.9, 1.0]})
    stats = compute_stats(nav)
    assert stats["total_return"] == pytest.approx(0.0)
    assert stats["annual_return"] == pytest.approx(0.0)
    assert stats["max_drawdown"] == pytest.approx(-0.25)


def test_compute_stats_monotonic_growth() -> None:
    nav = pl.DataFrame({"nav": [1.0, 1.1, 1.21]})
    stats = compute_stats(nav)
    assert stats["total_return"] == pytest.approx(0.21)
    assert stats["max_drawdown"] == pytest.approx(0.0)
    assert stats["calmar"] is None
