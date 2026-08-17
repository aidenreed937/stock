import polars as pl
import pytest

from stock_analytics.primitives.valuation import (
    calculate_dividend_spread,
    calculate_equity_risk_premium,
    calculate_ey_by_ratio,
    calculate_rolling_percentile,
)


def test_calculate_equity_risk_premium() -> None:
    df = pl.DataFrame(
        {
            "pe_ttm": [10.0, 20.0, 50.0],
            "cn_10y_bond_yield": [2.5, 2.5, 2.5],
        }
    )
    res = calculate_equity_risk_premium(df)
    assert "equity_risk_premium" in res.columns
    # 100/10 - 2.5 = 7.5; 100/20 - 2.5 = 2.5; 100/50 - 2.5 = -0.5
    assert res["equity_risk_premium"].to_list() == pytest.approx([7.5, 2.5, -0.5], rel=1e-4)

    # 空数据与缺少字段
    empty_df = pl.DataFrame()
    assert calculate_equity_risk_premium(empty_df).is_empty()
    missing_df = pl.DataFrame({"pe_ttm": [10.0]})
    assert "equity_risk_premium" not in calculate_equity_risk_premium(missing_df).columns


def test_calculate_ey_by_ratio() -> None:
    df = pl.DataFrame(
        {
            "pe_ttm": [10.0, 20.0],
            "cn_10y_bond_yield": [2.5, 2.5],
        }
    )
    res = calculate_ey_by_ratio(df)
    assert "ey_by_ratio" in res.columns
    # (100/10) / 2.5 = 4.0; (100/20) / 2.5 = 2.0
    assert res["ey_by_ratio"].to_list() == pytest.approx([4.0, 2.0], rel=1e-4)

    empty_df = pl.DataFrame()
    assert calculate_ey_by_ratio(empty_df).is_empty()


def test_calculate_dividend_spread() -> None:
    df = pl.DataFrame(
        {
            "dv_ratio": [4.5, 2.0],
            "cn_10y_bond_yield": [2.5, 2.5],
        }
    )
    res = calculate_dividend_spread(df)
    assert "dividend_bond_spread" in res.columns
    # 4.5 - 2.5 = 2.0; 2.0 - 2.5 = -0.5
    assert res["dividend_bond_spread"].to_list() == pytest.approx([2.0, -0.5])


def test_calculate_rolling_percentile() -> None:
    # 构造递增序列检验分位数
    values = [float(i) for i in range(1, 11)]
    df = pl.DataFrame({"pe_ttm": values, "pb": values})
    res = calculate_rolling_percentile(df, metric_cols=("pe_ttm", "pb"), window_days=10)
    assert "pe_ttm_percentile_10d" in res.columns
    assert "pb_percentile_10d" in res.columns
    # 最后一项应该为 100% 分位
    assert res["pe_ttm_percentile_10d"][-1] == pytest.approx(100.0)

    # 空数据和无对应列
    empty_df = pl.DataFrame()
    assert calculate_rolling_percentile(empty_df).is_empty()
    other_df = pl.DataFrame({"volume": [100]})
    assert calculate_rolling_percentile(other_df, metric_cols=("pe_ttm",)).columns == ["volume"]
