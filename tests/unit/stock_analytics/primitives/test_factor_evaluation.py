"""因子有效性检验原语 (factor_evaluation) 单测：前向收益与 Rank IC 评估。"""

import statistics

import polars as pl
import pytest

from stock_analytics.primitives.factor_evaluation import (
    add_forward_returns,
    cumulative_ic,
    ic_decay,
    ic_summary,
    rank_ic_series,
)

# ---------- add_forward_returns ----------


def test_add_forward_returns_computes_horizon_returns_per_symbol() -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["A", "A", "A", "B", "B", "B"],
            "trade_date": [1, 2, 3, 1, 2, 3],
            "close": [100.0, 110.0, 120.0, 200.0, 210.0, 220.0],
        }
    )
    result = add_forward_returns(frame, horizons=(1, 2), price_col="close")

    assert "fwd_ret_1d" in result.columns
    assert "fwd_ret_2d" in result.columns
    # A: 100->110=10%, 110->120=9.0909%, 末行 null；B 同理
    a_fwd1 = result.filter(pl.col("symbol") == "A")["fwd_ret_1d"].to_list()
    assert a_fwd1[:2] == pytest.approx([10.0, 9.0909], abs=1e-4)
    assert a_fwd1[2] is None
    b_fwd1 = result.filter(pl.col("symbol") == "B")["fwd_ret_1d"].to_list()
    assert b_fwd1[:2] == pytest.approx([5.0, 4.7619], abs=1e-4)
    assert b_fwd1[2] is None
    # 2 日前向：A 首行 (120/100-1)=20%
    a_fwd2 = result.filter(pl.col("symbol") == "A")["fwd_ret_2d"].to_list()
    assert a_fwd2[0] == pytest.approx(20.0, abs=1e-4)
    assert a_fwd2[1:] == [None, None]


def test_add_forward_returns_without_symbol_uses_whole_series() -> None:
    frame = pl.DataFrame({"trade_date": [1, 2, 3], "close": [100.0, 110.0, 120.0]})
    result = add_forward_returns(frame, horizons=(1,))
    vals = result["fwd_ret_1d"].to_list()
    assert vals[:2] == pytest.approx([10.0, 9.0909], abs=1e-4)
    assert vals[2] is None


def test_add_forward_returns_returns_unchanged_when_input_invalid() -> None:
    frame = pl.DataFrame({"trade_date": [1], "close": [100.0]})
    assert add_forward_returns(frame, price_col="missing").columns == frame.columns

    empty = pl.DataFrame(schema={"trade_date": pl.Int64, "close": pl.Float64})
    assert add_forward_returns(empty).is_empty()

    no_date = pl.DataFrame({"close": [100.0, 110.0]})
    assert add_forward_returns(no_date).columns == ["close"]


def test_add_forward_returns_fails_closed_on_non_positive_or_missing_price() -> None:
    frame = pl.DataFrame(
        {"symbol": ["A", "A", "A"], "trade_date": [1, 2, 3], "close": [0.0, 100.0, None]}
    )
    result = add_forward_returns(frame, horizons=(1,))
    # 首行价格非正、末行价格缺失 → 前向收益均为 null
    assert result["fwd_ret_1d"].to_list() == [None, None, None]


# ---------- rank_ic_series ----------


def test_rank_ic_series_computes_daily_spearman_ic_long_frame() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": ["d1", "d1", "d1", "d2", "d2", "d2"],
            "symbol": ["A", "B", "C", "A", "B", "C"],
            "f": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
            "fwd_ret_1d": [2.0, 4.0, 6.0, 3.0, 2.0, 1.0],
        }
    )
    ic = rank_ic_series(frame, "f", ["fwd_ret_1d"])

    assert ic.columns == ["trade_date", "horizon", "ic"]
    d1 = ic.filter(pl.col("trade_date") == "d1")["ic"][0]
    d2 = ic.filter(pl.col("trade_date") == "d2")["ic"][0]
    assert d1 == pytest.approx(1.0)
    assert d2 == pytest.approx(-1.0)


def test_rank_ic_series_supports_multiple_forward_columns() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": ["d1", "d1", "d1"],
            "f": [1.0, 2.0, 3.0],
            "fwd_ret_1d": [2.0, 4.0, 6.0],
            "fwd_ret_5d": [6.0, 4.0, 2.0],
        }
    )
    ic = rank_ic_series(frame, "f", ["fwd_ret_1d", "fwd_ret_5d"])
    assert ic.height == 2
    assert set(ic["horizon"].to_list()) == {"fwd_ret_1d", "fwd_ret_5d"}
    assert ic.filter(pl.col("horizon") == "fwd_ret_1d")["ic"][0] == pytest.approx(1.0)
    assert ic.filter(pl.col("horizon") == "fwd_ret_5d")["ic"][0] == pytest.approx(-1.0)


def test_rank_ic_series_ignores_null_factor_values() -> None:
    frame = pl.DataFrame(
        {
            "trade_date": ["d1", "d1", "d1", "d1"],
            "f": [1.0, 2.0, 3.0, None],
            "fwd_ret_1d": [2.0, 4.0, 6.0, 999.0],
        }
    )
    ic = rank_ic_series(frame, "f", ["fwd_ret_1d"])
    assert ic["ic"][0] == pytest.approx(1.0)


def test_rank_ic_series_normalizes_uncomputable_corr_to_null_not_nan() -> None:
    # 某日因子全 null（如整日缺 pe_ttm），polars corr 返回 NaN 而非 null
    frame = pl.DataFrame(
        {
            "trade_date": ["d1", "d1", "d1", "d2", "d2", "d2"],
            "f": [None, None, None, 1.0, 2.0, 3.0],
            "fwd_ret_1d": [1.0, 2.0, 3.0, 2.0, 4.0, 6.0],
        }
    )
    ic = rank_ic_series(frame, "f", ["fwd_ret_1d"])

    d1 = ic.filter(pl.col("trade_date") == "d1")["ic"][0]
    d2 = ic.filter(pl.col("trade_date") == "d2")["ic"][0]
    assert d1 is None
    assert d2 == pytest.approx(1.0)
    # ic 列不应含 NaN
    assert ic["ic"].is_nan().sum() == 0


def test_rank_ic_series_returns_empty_schema_when_input_invalid() -> None:
    empty = pl.DataFrame(schema={"trade_date": pl.String, "f": pl.Float64})
    out = rank_ic_series(empty, "f", ["fwd_ret_1d"])
    assert out.is_empty()
    assert out.columns == ["trade_date", "horizon", "ic"]

    frame = pl.DataFrame({"trade_date": ["d1"], "f": [1.0]})
    out_missing = rank_ic_series(frame, "f", ["missing"])
    assert out_missing.is_empty()
    assert out_missing.columns == ["trade_date", "horizon", "ic"]


# ---------- ic_summary / ic_decay / cumulative_ic ----------


def _ic_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": ["d1", "d2", "d3", "d4"],
            "horizon": ["fwd_ret_1d"] * 4,
            "ic": [0.05, 0.03, 0.04, 0.06],
        }
    )


def test_ic_summary_computes_icir_t_stat_and_ratios() -> None:
    summary = ic_summary(_ic_frame())

    assert summary.height == 1
    row = summary.row(0, named=True)
    vals = [0.05, 0.03, 0.04, 0.06]
    mean = statistics.fmean(vals)
    std = statistics.stdev(vals)
    assert row["n_days"] == 4
    assert row["ic_mean"] == pytest.approx(mean)
    assert row["ic_std"] == pytest.approx(std)
    assert row["icir"] == pytest.approx(mean / std)
    assert row["icir_annualized"] == pytest.approx(mean / std * 252**0.5)
    assert row["t_stat"] == pytest.approx(mean / std * 4**0.5)
    assert row["ic_positive_ratio"] == pytest.approx(1.0)
    assert row["cum_ic"] == pytest.approx(0.18)


def test_ic_summary_sorts_horizons_numerically() -> None:
    ic_df = pl.DataFrame(
        {
            "trade_date": ["d1", "d2", "d3"],
            "horizon": ["fwd_ret_20d", "fwd_ret_1d", "fwd_ret_5d"],
            "ic": [0.01, 0.02, 0.03],
        }
    )
    summary = ic_summary(ic_df)
    assert summary["horizon"].to_list() == ["fwd_ret_1d", "fwd_ret_5d", "fwd_ret_20d"]


def test_ic_summary_returns_null_icir_for_constant_ic() -> None:
    ic_df = pl.DataFrame(
        {
            "trade_date": ["d1", "d2", "d3"],
            "horizon": ["fwd_ret_1d"] * 3,
            "ic": [0.05, 0.05, 0.05],
        }
    )
    summary = ic_summary(ic_df)
    assert summary["ic_mean"][0] == pytest.approx(0.05)
    assert summary["icir"][0] is None
    assert summary["icir_annualized"][0] is None
    assert summary["t_stat"][0] is None


def test_ic_summary_returns_empty_schema_when_input_invalid() -> None:
    expected = [
        "horizon",
        "n_days",
        "ic_mean",
        "ic_std",
        "icir",
        "icir_annualized",
        "t_stat",
        "ic_positive_ratio",
        "cum_ic",
    ]
    assert ic_summary(pl.DataFrame()).columns == expected
    bad = pl.DataFrame({"trade_date": ["d1"], "ic": [0.1]})
    assert ic_summary(bad).columns == expected
    all_null = pl.DataFrame({"horizon": ["fwd_ret_1d"], "ic": [None]})
    assert ic_summary(all_null).columns == expected


def test_ic_decay_returns_mean_ic_subset() -> None:
    decay = ic_decay(_ic_frame())
    assert decay.columns == ["horizon", "ic_mean", "n_days"]
    assert decay["ic_mean"][0] == pytest.approx(0.045)


def test_cumulative_ic_cumulates_within_horizon() -> None:
    cum = cumulative_ic(_ic_frame())
    assert cum.columns == ["trade_date", "horizon", "cum_ic"]
    assert cum["cum_ic"].to_list() == pytest.approx([0.05, 0.08, 0.12, 0.18])

    assert cumulative_ic(pl.DataFrame()).is_empty()
