"""primitives 纯规则算子单测。"""

import polars as pl
import pytest

from stock_analytics.primitives.rules import (
    above_ma,
    at_rolling_high,
    at_rolling_low,
    daily_return,
    growth,
    percentile_rank,
    rolling_percentile,
    rolling_zscore,
    share,
)


def test_rolling_zscore_computes_standardized_value() -> None:
    frame = pl.DataFrame({"value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}).with_columns(
        rolling_zscore("value", 3)
    )

    # 窗口 [4, 5, 6]: mean=5, 样本标准差(ddof=1)=1, zscore=(6-5)/1=1.0
    assert frame["value_zscore_3d"][5] == pytest.approx(1.0)
    assert frame["value_zscore_3d"].null_count() == 2


def test_rolling_zscore_returns_none_for_constant_series() -> None:
    frame = pl.DataFrame({"value": [5.0, 5.0, 5.0, 5.0, 5.0]}).with_columns(
        rolling_zscore("value", 3)
    )

    assert frame["value_zscore_3d"].to_list() == [None, None, None, None, None]


def test_rolling_zscore_default_output_name() -> None:
    frame = pl.DataFrame({"close": list(range(1, 70))}).with_columns(rolling_zscore("close", 60))
    assert "close_zscore_60d" in frame.columns


def test_rolling_zscore_accepts_custom_output() -> None:
    frame = pl.DataFrame({"value": [1.0, 2.0, 3.0]}).with_columns(rolling_zscore("value", 3, "z"))

    assert "z" in frame.columns


def test_rolling_percentile_uses_rank_instead_of_min_max_position() -> None:
    frame = pl.DataFrame({"value": [1.0, 100.0, 2.0]}).with_columns(rolling_percentile("value", 3))

    assert frame["value_percentile_3d"][-1] == pytest.approx(50.0)


def test_rolling_percentile_uses_min_rank_for_ties() -> None:
    frame = pl.DataFrame({"value": [1.0, 2.0, 2.0]}).with_columns(rolling_percentile("value", 3))

    assert frame["value_percentile_3d"][-1] == pytest.approx(50.0)


def test_percentile_rank_uses_min_rank_for_ties_and_standard_boundaries() -> None:
    values = pl.Series([1.0, 2.0, 2.0, 4.0])

    assert percentile_rank(values, 4, current=1.0) == pytest.approx(0.0)
    assert percentile_rank(values, 4, current=2.0) == pytest.approx(33.3333333)
    assert percentile_rank(values, 4, current=4.0) == pytest.approx(100.0)


def test_percentile_rank_returns_none_for_single_sample_and_invalid_window() -> None:
    assert percentile_rank(pl.Series([1.0]), 1) is None
    with pytest.raises(ValueError, match="window must be positive"):
        percentile_rank(pl.Series([1.0]), 0)


def test_rolling_percentile_ignores_historical_nulls_when_current_value_exists() -> None:
    frame = pl.DataFrame({"value": [1.0, 2.0, None, 3.0, 4.0, None]}).with_columns(
        rolling_percentile("value", 5)
    )

    assert frame["value_percentile_5d"][4] == pytest.approx(100.0)
    assert frame["value_percentile_5d"][5] is None


def test_percentile_rank_requires_minimum_valid_ratio() -> None:
    assert percentile_rank(pl.Series([1.0, 2.0]), 5) is None
    assert percentile_rank(pl.Series([1.0, 2.0, 3.0, 4.0, 5.0]), 5) == 100.0


def test_growth_computes_period_over_period_change() -> None:
    frame = pl.DataFrame({"value": [100.0, 101.0, 121.0, 110.0]}).with_columns(growth("value", 2))

    assert frame["value_growth_2d"][:2].to_list() == [None, None]
    assert frame["value_growth_2d"][2:].to_list() == pytest.approx([0.21, 110.0 / 101.0 - 1.0])


def test_share_guards_non_positive_denominator() -> None:
    frame = pl.DataFrame({"count": [1, 2, 3], "total": [0, 4, -1]}).with_columns(
        share("count", "total", "ratio")
    )

    assert frame["ratio"].to_list() == [None, 0.5, None]


def test_daily_return_is_per_symbol() -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["A", "A", "B", "B"],
            "close": [10.0, 11.0, 20.0, 19.0],
        }
    ).with_columns(daily_return("close"))

    assert frame["close_return_1d"][0] is None
    assert frame["close_return_1d"][2] is None
    assert frame["close_return_1d"][1] == pytest.approx(0.1)
    assert frame["close_return_1d"][3] == pytest.approx(-0.05)


def test_above_ma_compares_close_to_rolling_mean_per_symbol() -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["A"] * 5,
            "close": [1.0, 2.0, 3.0, 4.0, 1.0],
        }
    ).with_columns(above_ma("close", 3))

    # 窗口未成型前为 None；第 5 行 close=1 < ma(2.67)
    assert frame["close_above_ma3"].to_list() == [None, None, True, True, False]


def test_at_rolling_high_and_low_per_symbol() -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["A"] * 4,
            "close": [3.0, 1.0, 2.0, 3.0],
        }
    ).with_columns(
        at_rolling_high("close", 3),
        at_rolling_low("close", 3),
    )

    # 窗口未成型前为 None；第 3 行 close=2 < 窗口高 3；第 4 行 close=3 == 窗口高 3
    assert frame["close_high_3d"].to_list() == [None, None, False, True]
    assert frame["close_low_3d"].to_list() == [None, None, False, False]
