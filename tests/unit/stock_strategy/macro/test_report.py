from datetime import date

import polars as pl
import pytest

from stock_strategy.macro.report import compute_stats, nav_from_close


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


def test_render_comparison_markdown_dynamic_columns() -> None:
    from stock_strategy.macro.report import render_comparison_markdown

    stats = {
        "中证全指": {
            "final_nav": 1.1,
            "total_return": 0.1,
            "annual_return": 0.05,
            "max_drawdown": -0.1,
            "annual_volatility": 0.15,
            "sharpe": 0.33,
            "calmar": 0.5,
        },
        "custom_strat": {
            "final_nav": 1.5,
            "total_return": 0.5,
            "annual_return": 0.2,
            "max_drawdown": -0.08,
            "annual_volatility": 0.12,
            "sharpe": 1.6,
            "calmar": 2.5,
        },
    }
    md = render_comparison_markdown(stats, image_rel_path="test.png")
    assert "中证全指 (基准)" in md
    assert "**custom_strat**" in md
    assert "1.500" in md


def test_create_strategy_factory() -> None:
    from stock_strategy.pool import create_strategy

    s = create_strategy("MacroRotationV4Strategy", ma_window=30)
    assert s is not None
    with pytest.raises(ValueError, match="未知策略类"):
        create_strategy("NonExistentStrategy")
