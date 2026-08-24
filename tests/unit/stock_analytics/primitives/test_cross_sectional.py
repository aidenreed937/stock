"""横截面因子工程与统计回归原语单测。"""

import polars as pl
import pytest

from stock_analytics.primitives.cross_sectional import (
    cross_sectional_ols,
    cross_sectional_zscore,
    mad_winsorize,
    quantile_bucket,
)


def test_mad_winsorize_clips_extreme_values_to_robust_upper_bound() -> None:
    frame = pl.DataFrame({"v": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 1000.0]})
    result = mad_winsorize(frame, ["v"])

    # median=6.0, MAD=3.0, upper = 6 + 3*1.4826*3 = 19.3434
    assert result["v_winsorized"].to_list()[:10] == pytest.approx(
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    )
    assert result["v_winsorized"][-1] == pytest.approx(19.3434, abs=1e-4)


def test_mad_winsorize_grouped_winsorizes_within_each_group() -> None:
    frame = pl.DataFrame(
        {
            "g": ["A"] * 5 + ["B"] * 5,
            "v": [1.0, 2.0, 3.0, 4.0, 100.0] + [1.0, 2.0, 3.0, 4.0, 500.0],
        }
    )
    result = mad_winsorize(frame, ["v"], group_by="g")

    group_a = result.filter(pl.col("g") == "A")["v_winsorized"].to_list()
    group_b = result.filter(pl.col("g") == "B")["v_winsorized"].to_list()
    # A: median=3, MAD=1, upper=3+3*1.4826=7.4478；B: median=3, MAD=1, upper 相同
    assert group_a[-1] == pytest.approx(7.4478, abs=1e-4)
    assert group_a == group_b


def test_mad_winsorize_keeps_original_when_mad_is_zero() -> None:
    frame = pl.DataFrame({"v": [5.0, 5.0, 5.0, 5.0]})
    result = mad_winsorize(frame, ["v"])

    assert result["v_winsorized"].to_list() == [5.0, 5.0, 5.0, 5.0]


def test_mad_winsorize_preserves_nulls_and_returns_empty_frame_unchanged() -> None:
    frame = pl.DataFrame({"v": [1.0, None, 100.0]})
    result = mad_winsorize(frame, ["v"])
    assert result["v_winsorized"][1] is None

    empty = pl.DataFrame(schema={"v": pl.Float64})
    assert mad_winsorize(empty, ["v"]).is_empty()


def test_cross_sectional_zscore_standardizes_across_section() -> None:
    frame = pl.DataFrame({"v": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = cross_sectional_zscore(frame, ["v"])

    # mean=3, 样本标准差(ddof=1)=sqrt(2.5)，末值 z=(5-3)/1.5811=1.2649
    assert result["v_cs_zscore"][0] == pytest.approx(-1.2649, abs=1e-4)
    assert result["v_cs_zscore"][2] == pytest.approx(0.0, abs=1e-9)
    assert result["v_cs_zscore"][4] == pytest.approx(1.2649, abs=1e-4)


def test_cross_sectional_zscore_grouped_is_industry_neutralized() -> None:
    frame = pl.DataFrame(
        {
            "industry": ["X"] * 3 + ["Y"] * 3,
            "pe": [10.0, 20.0, 30.0] + [1.0, 2.0, 3.0],
        }
    )
    result = cross_sectional_zscore(frame, ["pe"], group_by="industry")

    x_zscores = result.filter(pl.col("industry") == "X")["pe_cs_zscore"].to_list()
    y_zscores = result.filter(pl.col("industry") == "Y")["pe_cs_zscore"].to_list()
    # 两组各自标准化，避免绝对量级差异污染
    assert x_zscores == pytest.approx([-1.0, 0.0, 1.0], abs=1e-9)
    assert y_zscores == pytest.approx([-1.0, 0.0, 1.0], abs=1e-9)


def test_cross_sectional_zscore_returns_none_for_constant_group() -> None:
    frame = pl.DataFrame({"v": [5.0, 5.0, 5.0]})
    result = cross_sectional_zscore(frame, ["v"])

    assert result["v_cs_zscore"].to_list() == [None, None, None]


def test_quantile_bucket_maps_equal_frequency_bins() -> None:
    frame = pl.DataFrame({"v": list(range(1, 101))})
    result = quantile_bucket(frame, "v", n_bins=10)

    buckets = result["v_bucket_10"].to_list()
    # rank 1-10 -> 1，rank 11-20 -> 2，...，rank 91-100 -> 10
    assert buckets[:10] == [1] * 10
    assert buckets[10:20] == [2] * 10
    assert buckets[-10:] == [10] * 10


def test_quantile_bucket_preserves_nulls_and_supports_grouping() -> None:
    frame = pl.DataFrame({"g": ["A"] * 6 + ["B"] * 6, "v": [None, 2.0, 3.0, 4.0, 5.0, 6.0] * 2})
    result = quantile_bucket(frame, "v", n_bins=3, group_by="g")

    group_a = result.filter(pl.col("g") == "A")["v_bucket_3"].to_list()
    assert group_a[0] is None
    # 组内 5 个有效样本等分 3 箱：rank 1-2 -> 1，rank 3-4 -> 2，rank 5 -> 3
    assert group_a[1:] == [1, 1, 2, 2, 3]


def test_quantile_bucket_rejects_invalid_bin_count() -> None:
    frame = pl.DataFrame({"v": [1.0, 2.0]})
    with pytest.raises(ValueError, match="n_bins must be positive"):
        quantile_bucket(frame, "v", n_bins=0)


def test_cross_sectional_ols_fits_exact_linear_relationship() -> None:
    frame = pl.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0], "y": [3.0, 5.0, 7.0, 9.0, 11.0]})
    result = cross_sectional_ols(frame, "x", "y")

    assert result["y_on_x_slope"][0] == pytest.approx(2.0)
    assert result["y_on_x_intercept"][0] == pytest.approx(1.0)
    assert result["y_on_x_r2"][0] == pytest.approx(1.0)
    assert result["y_on_x_residual"].to_list() == pytest.approx([0.0] * 5, abs=1e-9)


def test_cross_sectional_ols_computes_residuals_and_r2() -> None:
    frame = pl.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 5.0, 8.0]})
    result = cross_sectional_ols(frame, "x", "y")

    # slope = cov/var = 3.1667/1.6667 = 1.9, intercept = 0, r2 = 1 - 0.7/18.75
    assert result["y_on_x_slope"][0] == pytest.approx(1.9)
    assert result["y_on_x_intercept"][0] == pytest.approx(0.0, abs=1e-9)
    assert result["y_on_x_r2"][0] == pytest.approx(1 - 0.7 / 18.75, abs=1e-6)
    assert result["y_on_x_residual"].to_list() == pytest.approx([0.1, 0.2, -0.7, 0.4], abs=1e-9)
    # 拟合值 = y - residual
    fitted = result["y_on_x_fitted"].to_list()
    assert fitted == pytest.approx([1.9, 3.8, 5.7, 7.6], abs=1e-9)


def test_cross_sectional_ols_fits_per_group() -> None:
    frame = pl.DataFrame(
        {
            "g": ["A"] * 5 + ["B"] * 5,
            "x": list(range(1, 6)) + list(range(1, 6)),
            "y": [2.0, 4.0, 6.0, 8.0, 10.0] + [3.0, 6.0, 9.0, 12.0, 15.0],
        }
    )
    result = cross_sectional_ols(frame, "x", "y", group_by="g").unique(subset=["g"])

    group_a = result.filter(pl.col("g") == "A")
    group_b = result.filter(pl.col("g") == "B")
    assert group_a["y_on_x_slope"][0] == pytest.approx(2.0)
    assert group_a["y_on_x_intercept"][0] == pytest.approx(0.0, abs=1e-9)
    assert group_b["y_on_x_slope"][0] == pytest.approx(3.0)
    assert group_b["y_on_x_intercept"][0] == pytest.approx(0.0, abs=1e-9)


def test_cross_sectional_ols_returns_none_for_degenerate_variance() -> None:
    frame = pl.DataFrame({"x": [5.0, 5.0, 5.0], "y": [1.0, 2.0, 3.0]})
    result = cross_sectional_ols(frame, "x", "y")

    assert result["y_on_x_slope"].to_list() == [None, None, None]
    assert result["y_on_x_intercept"].to_list() == [None, None, None]
    assert result["y_on_x_r2"].to_list() == [None, None, None]


def test_cross_sectional_ols_returns_none_for_insufficient_samples() -> None:
    frame = pl.DataFrame({"g": ["A", "B", "B"], "x": [1.0, 1.0, 2.0], "y": [1.0, 2.0, 3.0]})
    result = cross_sectional_ols(frame, "x", "y", group_by="g")

    # A 组仅 1 个样本，整组缺失；B 组正常拟合
    assert result.filter(pl.col("g") == "A")["y_on_x_slope"].to_list() == [None]
    assert result.filter(pl.col("g") == "B")["y_on_x_slope"].to_list() == [1.0, 1.0]


def test_cross_sectional_ols_handles_nulls_and_missing_columns() -> None:
    frame = pl.DataFrame({"x": [1.0, None, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]})
    result = cross_sectional_ols(frame, "x", "y")

    # x 缺失行不参与拟合，残差与拟合值透传 None
    assert result["y_on_x_residual"][1] is None
    assert result["y_on_x_r2"][0] == pytest.approx(1.0)

    empty = pl.DataFrame(schema={"x": pl.Float64, "y": pl.Float64})
    assert cross_sectional_ols(empty, "x", "y").is_empty()
    assert cross_sectional_ols(frame, "x", "missing").columns == frame.columns


def test_cross_sectional_ols_cov_is_symmetric_with_integer_columns() -> None:
    # 整型 x 列（如成交量/序号）经 cast 后，协方差与方差的类型/缺失过滤完全对称
    frame = pl.DataFrame({"x": [1, None, 3, 4], "y": [2, 4, 6, 8]})
    result = cross_sectional_ols(frame, "x", "y")

    # 有效样本对 (1,2),(3,6),(4,8)：slope=2, intercept=0, r2=1
    assert result["y_on_x_slope"][0] == pytest.approx(2.0)
    assert result["y_on_x_intercept"][0] == pytest.approx(0.0, abs=1e-9)
    assert result["y_on_x_r2"][0] == pytest.approx(1.0)
