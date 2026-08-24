"""杜邦拆解与财报质量原语单测。"""

import polars as pl
import pytest

from stock_analytics.primitives.fundamental import (
    dupond_decomposition,
    earnings_quality,
    growth_acceleration,
)


def test_dupond_decomposition_satisfies_product_identity() -> None:
    # revenue=100, n_income=10, total_assets=200, equity=50
    frame = pl.DataFrame(
        {
            "n_income": [10.0],
            "revenue": [100.0],
            "total_assets": [200.0],
            "total_hldr_eqy_exc_min_int": [50.0],
        }
    )
    result = dupond_decomposition(frame)

    assert result["net_profit_margin"][0] == pytest.approx(0.1)
    assert result["asset_turnover"][0] == pytest.approx(0.5)
    assert result["equity_multiplier"][0] == pytest.approx(4.0)
    assert result["roe_dupont"][0] == pytest.approx(0.2)
    assert result["roe_dupont"][0] == pytest.approx(
        result["net_profit_margin"][0]
        * result["asset_turnover"][0]
        * result["equity_multiplier"][0]
    )


def test_dupond_decomposition_fail_closed_on_zero_or_negative_denominator() -> None:
    frame = pl.DataFrame(
        {
            "n_income": [10.0, 10.0, 10.0],
            "revenue": [0.0, 100.0, 100.0],
            "total_assets": [200.0, 0.0, 200.0],
            "total_hldr_eqy_exc_min_int": [50.0, 50.0, -50.0],
        }
    )
    result = dupond_decomposition(frame)

    # revenue=0 -> net_profit_margin null
    assert result["net_profit_margin"][0] is None
    # total_assets=0 -> asset_turnover null
    assert result["asset_turnover"][1] is None
    # equity=-50（负分母）-> equity_multiplier null 且 roe_dupont null
    assert result["equity_multiplier"][2] is None
    assert result["roe_dupont"][2] is None


def test_dupond_decomposition_null_propagates_to_roe() -> None:
    frame = pl.DataFrame(
        {
            "n_income": [10.0],
            "revenue": [100.0],
            "total_assets": [200.0],
            "total_hldr_eqy_exc_min_int": [0.0],
        }
    )
    result = dupond_decomposition(frame)

    assert result["equity_multiplier"][0] is None
    assert result["roe_dupont"][0] is None


def test_dupond_decomposition_empty_frame_returns_original() -> None:
    frame = pl.DataFrame(
        {
            "n_income": [],
            "revenue": [],
            "total_assets": [],
            "total_hldr_eqy_exc_min_int": [],
        }
    )
    result = dupond_decomposition(frame)

    assert result is frame


def test_dupond_decomposition_missing_column_returns_original() -> None:
    frame = pl.DataFrame({"n_income": [10.0], "revenue": [100.0]})
    result = dupond_decomposition(frame)

    assert result is frame
    assert "net_profit_margin" not in result.columns


def test_earnings_quality_computes_ocf_to_net_profit() -> None:
    frame = pl.DataFrame({"n_income": [10.0], "n_cashflow_act": [25.0]})
    result = earnings_quality(frame)

    assert result["ocf_to_net_profit"][0] == pytest.approx(2.5)


def test_earnings_quality_fail_closed_on_nonpositive_net_income() -> None:
    frame = pl.DataFrame({"n_income": [0.0, -5.0], "n_cashflow_act": [25.0, 25.0]})
    result = earnings_quality(frame)

    assert result["ocf_to_net_profit"][0] is None
    assert result["ocf_to_net_profit"][1] is None


def test_earnings_quality_empty_frame_returns_original() -> None:
    frame = pl.DataFrame({"n_income": [], "n_cashflow_act": []})
    result = earnings_quality(frame)

    assert result is frame


def test_earnings_quality_missing_column_returns_original() -> None:
    frame = pl.DataFrame({"n_income": [10.0]})
    result = earnings_quality(frame)

    assert result is frame
    assert "ocf_to_net_profit" not in result.columns


def test_growth_acceleration_deltas_across_levels() -> None:
    frame = pl.DataFrame({"level": [1, 2], "yoy_growth": [20.0, 15.0]})
    result = growth_acceleration(frame, "yoy_growth")

    # level=1 行：20 - 15 = 5；level=2 行无更早一期 -> null
    assert result["yoy_growth_accel"][0] == pytest.approx(5.0)
    assert result["yoy_growth_accel"][1] is None


def test_growth_acceleration_null_when_previous_level_missing() -> None:
    frame = pl.DataFrame({"level": [1], "yoy_growth": [20.0]})
    result = growth_acceleration(frame, "yoy_growth")

    assert result["yoy_growth_accel"][0] is None


def test_growth_acceleration_per_symbol_panel() -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["A", "A", "B", "B"],
            "level": [1, 2, 1, 2],
            "yoy_growth": [20.0, 15.0, 30.0, 10.0],
        }
    )
    result = growth_acceleration(frame, "yoy_growth")

    a1 = result.filter((pl.col("symbol") == "A") & (pl.col("level") == 1))["yoy_growth_accel"][0]
    b1 = result.filter((pl.col("symbol") == "B") & (pl.col("level") == 1))["yoy_growth_accel"][0]
    assert a1 == pytest.approx(5.0)
    assert b1 == pytest.approx(20.0)


def test_growth_acceleration_unsorted_input() -> None:
    frame = pl.DataFrame({"level": [2, 1], "yoy_growth": [15.0, 20.0]})
    result = growth_acceleration(frame, "yoy_growth")

    # 输入行序与 level 无关，结果按 level 语义对齐
    assert result["yoy_growth_accel"][0] is None
    assert result["yoy_growth_accel"][1] == pytest.approx(5.0)


def test_growth_acceleration_empty_frame_returns_original() -> None:
    frame = pl.DataFrame({"level": [], "yoy_growth": []})
    result = growth_acceleration(frame, "yoy_growth")

    assert result is frame


def test_growth_acceleration_missing_column_returns_original() -> None:
    frame = pl.DataFrame({"yoy_growth": [20.0]})
    result = growth_acceleration(frame, "yoy_growth")

    assert result is frame
    assert "yoy_growth_accel" not in result.columns
