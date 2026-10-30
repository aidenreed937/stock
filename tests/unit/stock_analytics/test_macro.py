import polars as pl
import pytest

from stock_analytics.primitives.macro import (
    calculate_macro_spread,
    calculate_securitization_ratio,
    calculate_yield_curve_slope,
    consecutive_days,
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


def test_consecutive_days_cumulative_and_reset() -> None:
    df = pl.DataFrame(
        {
            "trade_date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "insider_net_score": [85.0, 90.0, 70.0, 88.0],
        }
    )
    res = consecutive_days(df, "insider_net_score", 80.0)
    # 85>=80(1)，90>=80(2)，70<80 清零(0)，88>=80(1)
    assert res["insider_net_score_consec"].to_list() == [1, 2, 0, 1]
    # 原列只读、不覆盖
    assert "insider_net_score" in res.columns
    assert res["insider_net_score"].to_list() == [85.0, 90.0, 70.0, 88.0]


def test_consecutive_days_null_breaks_run() -> None:
    df = pl.DataFrame(
        {
            "trade_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "smart_money_pct": [85.0, None, 88.0],
        }
    )
    res = consecutive_days(df, "smart_money_pct", 80.0)
    # 数据缺失按未达标处理，避免跨缺口误续连：85(1), None->0, 88(1)
    assert res["smart_money_pct_consec"].to_list() == [1, 0, 1]


def test_consecutive_days_threshold_boundary() -> None:
    df = pl.DataFrame(
        {
            "trade_date": ["2024-01-01", "2024-01-02"],
            "insider_net_score": [80.0, 79.99],
        }
    )
    res = consecutive_days(df, "insider_net_score", 80.0)
    # 恰好等于阈值算达标，小于阈值不达标
    assert res["insider_net_score_consec"].to_list() == [1, 0]


def test_consecutive_days_unknown_column_is_noop() -> None:
    df = pl.DataFrame({"trade_date": ["2024-01-01"], "a": [1.0]})
    res = consecutive_days(df, "missing_col", 80.0)
    assert "missing_col_consec" not in res.columns
    assert res.columns == ["trade_date", "a"]
