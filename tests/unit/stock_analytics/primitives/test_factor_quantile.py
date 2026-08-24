"""因子有效性检验原语 (factor_quantile) 单测：分层收益与多空组合。"""

import polars as pl
import pytest

from stock_analytics.primitives.factor_quantile import (
    quantile_forward_returns,
    quantile_summary,
)


def _monotone_panel() -> pl.DataFrame:
    rows = []
    for d in range(4):
        for i in range(1, 11):
            rows.append((f"d{d}", f"S{i}", float(i), float(i) * 2.0))
    return pl.DataFrame(rows, schema=["trade_date", "symbol", "f", "fwd_ret_1d"], orient="row")


def test_quantile_forward_returns_buckets_cross_sectionally() -> None:
    panel = quantile_forward_returns(_monotone_panel(), "f", "fwd_ret_1d", n_bins=5)

    assert panel.columns == ["trade_date", "bucket", "fwd_mean", "fwd_median", "n"]
    assert panel.height == 4 * 5
    assert set(panel["bucket"].unique().to_list()) == {1, 2, 3, 4, 5}
    # 每日期桶均值严格递增（factor 与 fwd 完全单调）
    for _, group in panel.group_by("trade_date", maintain_order=True):
        means = group["fwd_mean"].to_list()
        assert means == sorted(means)
        assert group["n"].to_list() == [2] * 5


def test_quantile_forward_returns_excludes_null_factor_rows() -> None:
    panel = quantile_forward_returns(_monotone_panel(), "f", "fwd_ret_1d", n_bins=5)
    assert panel.height == 20

    bad = _monotone_panel().with_columns(
        pl.when((pl.col("symbol") == "S1") & (pl.col("trade_date") == "d0"))
        .then(None)
        .otherwise(pl.col("f"))
        .alias("f")
    )
    panel_bad = quantile_forward_returns(bad, "f", "fwd_ret_1d", n_bins=5)
    # 剔除 1 个缺失因子行 → 总样本数 40-1 = 39（缺失行不参与任何分箱）
    assert panel_bad["n"].sum() == 39


def test_quantile_forward_returns_rejects_invalid_bin_count() -> None:
    with pytest.raises(ValueError, match="n_bins must be positive"):
        quantile_forward_returns(_monotone_panel(), "f", "fwd_ret_1d", n_bins=0)


def test_quantile_forward_returns_returns_empty_schema_when_input_invalid() -> None:
    empty = pl.DataFrame(schema={"trade_date": pl.String, "f": pl.Float64})
    out = quantile_forward_returns(empty, "f", "fwd_ret_1d", n_bins=5)
    assert out.is_empty()
    assert out.columns == ["trade_date", "bucket", "fwd_mean", "fwd_median", "n"]


def test_quantile_summary_reports_monotonicity_and_long_short() -> None:
    panel = quantile_forward_returns(_monotone_panel(), "f", "fwd_ret_1d", n_bins=5)
    summary = quantile_summary(panel, n_bins=5)

    by_bucket = summary["by_bucket"]
    assert by_bucket.columns == ["bucket", "n_days", "n_stocks", "weighted_mean", "median_of_means"]
    assert by_bucket["bucket"].to_list() == [1, 2, 3, 4, 5]
    # 完全单调 → Spearman = 1.0；Top(19.0) - Bottom(3.0) = 16.0
    assert summary["monotonicity_spearman"] == pytest.approx(1.0)
    assert summary["bottom_bucket_mean"] == pytest.approx(3.0)
    assert summary["top_bucket_mean"] == pytest.approx(19.0)
    assert summary["long_short_mean"] == pytest.approx(16.0)

    series = summary["long_short_series"]
    assert series.columns == ["trade_date", "top", "bottom", "spread", "cum_spread", "drawdown"]
    assert series["spread"].to_list() == pytest.approx([16.0] * 4)
    assert series["cum_spread"].to_list() == pytest.approx([16.0, 32.0, 48.0, 64.0])
    # 单调上行 → 无回撤
    assert summary["long_short_max_drawdown"] == pytest.approx(0.0)


def test_quantile_summary_tracks_long_short_drawdown_on_inverted_date() -> None:
    rows = []
    for d in range(3):
        for i in range(1, 11):
            rows.append((f"d{d}", f"S{i}", float(i), float(i) * 2.0))
    # 末日因子与收益反向：多空价差为 -16
    for i in range(1, 11):
        rows.append(("d3", f"S{i}", float(i), -float(i) * 2.0))
    frame = pl.DataFrame(rows, schema=["trade_date", "symbol", "f", "fwd_ret_1d"], orient="row")
    panel = quantile_forward_returns(frame, "f", "fwd_ret_1d", n_bins=5)
    summary = quantile_summary(panel, n_bins=5)

    series = summary["long_short_series"]
    assert series["spread"].to_list() == pytest.approx([16.0, 16.0, 16.0, -16.0])
    assert series["cum_spread"].to_list() == pytest.approx([16.0, 32.0, 48.0, 32.0])
    assert series["drawdown"].to_list() == pytest.approx([0.0, 0.0, 0.0, -16.0])
    assert summary["long_short_mean"] == pytest.approx(8.0)
    assert summary["long_short_max_drawdown"] == pytest.approx(-16.0)


def test_quantile_summary_returns_empty_fallback_when_input_invalid() -> None:
    summary = quantile_summary(pl.DataFrame(), n_bins=5)
    assert summary["by_bucket"].is_empty()
    assert summary["long_short_series"].is_empty()
    assert summary["monotonicity_spearman"] is None
    assert summary["long_short_mean"] is None
    assert summary["long_short_max_drawdown"] is None
