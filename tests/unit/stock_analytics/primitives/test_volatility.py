"""波动率与 K 线形态原语单测。"""

import polars as pl
import pytest

from stock_analytics.primitives.volatility import (
    calculate_garman_klass_volatility,
    calculate_parkinson_volatility,
    calculate_shadow_ratio,
)


def test_parkinson_volatility_annualizes_extreme_value_variance() -> None:
    # high=110, low=90 恒定，window=2：ln(110/90)^2/(4ln2)=0.0145244，年化 * sqrt(252)
    frame = pl.DataFrame({"high": [110.0, 110.0], "low": [90.0, 90.0]})
    result = calculate_parkinson_volatility(frame, window=2)

    assert result["parkinson_vol_2d"][0] is None
    assert result["parkinson_vol_2d"][1] == pytest.approx(1.91317, abs=1e-4)


def test_parkinson_volatility_supports_percentage_output() -> None:
    frame = pl.DataFrame({"high": [110.0, 110.0], "low": [90.0, 90.0]})
    result = calculate_parkinson_volatility(frame, window=2, as_percentage=True)

    assert result["parkinson_vol_2d"][1] == pytest.approx(191.317, abs=1e-2)


def test_parkinson_volatility_per_symbol_panel() -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["A", "A", "B", "B"],
            "high": [110.0, 110.0, 60.0, 60.0],
            "low": [90.0, 90.0, 40.0, 40.0],
        }
    )
    result = calculate_parkinson_volatility(frame, window=2)

    assert result["parkinson_vol_2d"][1] == pytest.approx(1.91317, abs=1e-4)
    # B: ln(60/40)^2/(4ln2)=0.0592968，sqrt * sqrt(252)=3.86555
    assert result["parkinson_vol_2d"][3] == pytest.approx(3.86555, abs=1e-4)


def test_garman_klass_volatility_combines_ohlc() -> None:
    # window=1：0.5*ln(110/90)^2 - (2ln2-1)*ln(105/100)^2 = 0.0192148
    frame = pl.DataFrame(
        {
            "high": [110.0, 110.0],
            "low": [90.0, 90.0],
            "open": [100.0, 100.0],
            "close": [105.0, 105.0],
        }
    )
    result = calculate_garman_klass_volatility(frame, window=1)

    assert result["garman_klass_vol_1d"][0] == pytest.approx(2.20048, abs=1e-4)
    assert result["garman_klass_vol_1d"][1] == pytest.approx(2.20048, abs=1e-4)


def test_garman_klass_volatility_clips_negative_daily_variance() -> None:
    # 收盘价相对开盘价移动幅度显著大于 High/Low 波幅，构造理论负方差，
    # 结果应被截断为 0 而非 NaN
    frame = pl.DataFrame({"high": [100.0], "low": [99.9], "open": [100.0], "close": [100.5]})
    result = calculate_garman_klass_volatility(frame, window=1)

    assert result["garman_klass_vol_1d"][0] == pytest.approx(0.0, abs=1e-12)


def test_shadow_ratio_decomposes_candle_into_three_parts() -> None:
    # open=100, close=105, high=110, low=90：上影 5/20、下影 10/20、实体 5/20
    frame = pl.DataFrame({"high": [110.0], "low": [90.0], "open": [100.0], "close": [105.0]})
    result = calculate_shadow_ratio(frame)

    assert result["upper_shadow_ratio"][0] == pytest.approx(0.25)
    assert result["lower_shadow_ratio"][0] == pytest.approx(0.5)
    assert result["body_ratio"][0] == pytest.approx(0.25)


def test_shadow_ratio_handles_bearish_and_doji_candles() -> None:
    bearish = pl.DataFrame({"high": [115.0], "low": [95.0], "open": [110.0], "close": [100.0]})
    result_bear = calculate_shadow_ratio(bearish)
    assert result_bear["upper_shadow_ratio"][0] == pytest.approx(0.25)
    assert result_bear["body_ratio"][0] == pytest.approx(0.5)

    doji = pl.DataFrame({"high": [110.0], "low": [100.0], "open": [105.0], "close": [105.0]})
    result_doji = calculate_shadow_ratio(doji)
    assert result_doji["upper_shadow_ratio"][0] == pytest.approx(0.5)
    assert result_doji["body_ratio"][0] == pytest.approx(0.0)


def test_shadow_ratio_returns_none_for_flat_bar_and_missing_columns() -> None:
    flat = pl.DataFrame({"high": [100.0], "low": [100.0], "open": [100.0], "close": [100.0]})
    result_flat = calculate_shadow_ratio(flat)
    assert result_flat["upper_shadow_ratio"][0] is None

    frame = pl.DataFrame({"high": [110.0], "low": [90.0], "open": [100.0]})
    assert calculate_shadow_ratio(frame).columns == frame.columns


def test_volatility_estimators_return_empty_frame_unchanged() -> None:
    empty = pl.DataFrame(schema={"high": pl.Float64, "low": pl.Float64})
    assert calculate_parkinson_volatility(empty).is_empty()
    assert calculate_garman_klass_volatility(empty).is_empty()


def test_parkinson_volatility_guards_non_positive_high() -> None:
    # high<=0 时 ln(High/Low) 无定义：脏数据行输出缺失（非 NaN 污染），
    # 且 null 在滚动窗口内传播，脏数据离开窗口后恢复计算
    frame = pl.DataFrame({"high": [0.0, 110.0, 110.0], "low": [90.0, 90.0, 90.0]})
    result = calculate_parkinson_volatility(frame, window=2)

    assert result["parkinson_vol_2d"][0] is None
    # 窗口含脏数据行 -> null 传播
    assert result["parkinson_vol_2d"][1] is None
    # 脏数据离开 2 日窗口 -> 恢复正常估计
    assert result["parkinson_vol_2d"][2] == pytest.approx(1.91317, abs=1e-4)


def test_garman_klass_volatility_guards_non_positive_close() -> None:
    # close<=0 时 ln(Close/Open) 无定义：脏数据行输出缺失，窗口内传播
    frame = pl.DataFrame(
        {
            "high": [110.0, 110.0],
            "low": [90.0, 90.0],
            "open": [100.0, 100.0],
            "close": [0.0, 105.0],
        }
    )
    result = calculate_garman_klass_volatility(frame, window=1)

    assert result["garman_klass_vol_1d"][0] is None
    # window=1 不含历史行，干净行直接恢复计算
    assert result["garman_klass_vol_1d"][1] == pytest.approx(2.20048, abs=1e-4)
