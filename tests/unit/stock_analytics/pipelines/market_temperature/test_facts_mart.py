"""市场温度计读取 Analytics Mart 的回归测试。"""

from datetime import date, timedelta

import polars as pl
import pytest

from stock_analytics.pipelines.market_temperature.facts_mart import try_get_market_daily_fact
from stock_reporting.interpretation.market_temperature.config import MetricInputConfig


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


def test_margin_growth_60d_uses_long_window() -> None:
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=index) for index in range(62)]
    balances = [100.0 + index for index in range(62)]
    frame = pl.DataFrame({"trade_date": dates, "margin_balance": balances})

    fact = try_get_market_daily_fact(
        frame,
        "fund_flow",
        MetricInputConfig("margin_balance_growth_60d"),
        dates[-1],
        expected_trade_date=dates[-1],
    )

    assert fact is not None
    assert fact["value_float"] == pytest.approx(161.0 / 101.0 - 1.0)


def test_main_money_cumulative_share_uses_latest_20_valid_days() -> None:
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=index) for index in range(21)]
    frame = pl.DataFrame(
        {
            "trade_date": dates,
            "total_turnover": [100.0] * 21,
            "main_net_inflow": [1.0] * 20 + [5.0],
        }
    )

    fact = try_get_market_daily_fact(
        frame,
        "fund_flow",
        MetricInputConfig("main_money_net_inflow_share_20d_cum"),
        dates[-1],
        expected_trade_date=dates[-1],
    )

    assert fact is not None
    assert fact["value_float"] == pytest.approx(24.0 / 2000.0)
    assert "window_start=2026-01-02" in fact["note"]
    assert "window_end=2026-01-21" in fact["note"]


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


@pytest.mark.parametrize(
    ("metric_id", "value"),
    [("return_20d", 0.12), ("rsi_14d", 58.0), ("ma_bias_20d", 0.03)],
)
def test_technical_metrics_map_to_materialized_market_daily_columns(
    metric_id: str, value: float
) -> None:
    target = date(2026, 8, 17)
    frame = pl.DataFrame({"trade_date": [target], metric_id: [value]})

    fact = try_get_market_daily_fact(
        frame,
        "technical",
        MetricInputConfig(metric_id),
        target,
        expected_trade_date=target,
    )

    assert fact is not None
    assert fact["data_source"] == "mart"
    assert fact["value_float"] == pytest.approx(value)
