import polars as pl
import pytest

from stock_analytics.primitives.macro import (
    calculate_macro_spread,
    calculate_securitization_ratio,
    calculate_yield_curve_slope,
)


def test_calculate_securitization_ratio() -> None:
    # 正常情况：市值 97.7万亿，GDP 100万亿 -> 97.7%
    ratio = calculate_securitization_ratio(977000.0, 1000000.0)
    assert round(ratio, 2) == 97.7

    # 边界情况：GDP 为 0 或负数
    assert calculate_securitization_ratio(100.0, 0.0) == 0.0
    assert calculate_securitization_ratio(100.0, -500.0) == 0.0


def test_calculate_yield_curve_slope() -> None:
    df = pl.DataFrame(
        {
            "t10y": [2.5, 2.6, 2.7],
            "t2y": [1.5, 1.8, 2.0],
        }
    )
    res = calculate_yield_curve_slope(df)
    assert "yield_curve_slope_10y_2y" in res.columns
    assert res["yield_curve_slope_10y_2y"].to_list() == pytest.approx([1.0, 0.8, 0.7])

    # 空数据和缺列
    empty_df = pl.DataFrame()
    assert calculate_yield_curve_slope(empty_df).is_empty()
    missing_df = pl.DataFrame({"t10y": [2.5]})
    assert "yield_curve_slope_10y_2y" not in calculate_yield_curve_slope(missing_df).columns


def test_calculate_macro_spread() -> None:
    df = pl.DataFrame(
        {
            "aaa_corp_yield": [3.5, 3.8],
            "cn_10y_bond_yield": [2.0, 2.1],
        }
    )
    res = calculate_macro_spread(
        df,
        higher_rate_col="aaa_corp_yield",
        lower_rate_col="cn_10y_bond_yield",
        spread_col_name="credit_spread",
    )
    assert "credit_spread" in res.columns
    assert res["credit_spread"].to_list() == pytest.approx([1.5, 1.7])
