"""市场温度计读取 Analytics Mart 的回归测试。"""

from datetime import date, timedelta

import polars as pl
import pytest

from stock.analytics.market_temperature.config import MetricInputConfig
from stock.analytics.market_temperature.facts_mart import try_get_market_daily_fact


def test_stale_market_daily_falls_back_to_metric_engine() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 14)],
            "advance_ratio": [0.6],
        }
    )

    fact = try_get_market_daily_fact(
        frame,
        "sentiment",
        MetricInputConfig("advance_share"),
        date(2026, 8, 17),
        expected_trade_date=date(2026, 8, 17),
    )

    assert fact is None


def test_current_market_daily_returns_fact() -> None:
    target = date(2026, 8, 17)
    frame = pl.DataFrame({"trade_date": [target], "advance_ratio": [0.6]})

    fact = try_get_market_daily_fact(
        frame,
        "sentiment",
        MetricInputConfig("advance_share"),
        target,
        expected_trade_date=target,
    )

    assert fact is not None
    assert fact["value_float"] == pytest.approx(0.6)
    assert fact["status"] == "ok"


def test_margin_zscore_requires_full_60_observations() -> None:
    start = date(2026, 1, 1)
    short_frame = pl.DataFrame(
        {
            "trade_date": [start + timedelta(days=index) for index in range(59)],
            "margin_buy_ratio": [float(index) for index in range(59)],
        }
    )

    fact = try_get_market_daily_fact(
        short_frame,
        "fund_flow",
        MetricInputConfig("margin_buy_share_zscore_60d"),
        short_frame["trade_date"][-1],
        expected_trade_date=short_frame["trade_date"][-1],
    )

    assert fact is None


def test_margin_growth_uses_row_aligned_20_period_shift() -> None:
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=index) for index in range(22)]
    balances = [100.0 + index for index in range(22)]
    balances[10] = None
    frame = pl.DataFrame({"trade_date": dates, "margin_balance": balances})

    fact = try_get_market_daily_fact(
        frame,
        "fund_flow",
        MetricInputConfig("margin_balance_growth_20d"),
        dates[-1],
        expected_trade_date=dates[-1],
    )

    assert fact is not None
    assert fact["value_float"] == pytest.approx(121.0 / 101.0 - 1.0)


def test_new_high_share_maps_to_mart_wide_column() -> None:
    target = date(2026, 8, 17)
    frame = pl.DataFrame({"trade_date": [target], "new_high_252d_ratio": [0.08]})

    fact = try_get_market_daily_fact(
        frame,
        "trend",
        MetricInputConfig("new_high_share_252d"),
        target,
        expected_trade_date=target,
    )

    assert fact is not None
    assert fact["value_float"] == pytest.approx(0.08)


def test_new_low_share_maps_to_mart_wide_column() -> None:
    target = date(2026, 8, 17)
    frame = pl.DataFrame({"trade_date": [target], "new_low_252d_ratio": [0.02]})

    fact = try_get_market_daily_fact(
        frame,
        "trend",
        MetricInputConfig("new_low_share_252d"),
        target,
        expected_trade_date=target,
    )

    assert fact is not None
    assert fact["value_float"] == pytest.approx(0.02)
