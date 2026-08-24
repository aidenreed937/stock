"""截面中性化与正交化原语 (neutralization) 单测。"""

import numpy as np
import polars as pl

from stock_analytics.primitives.neutralization import (
    cross_sectional_neutralize,
    cross_sectional_orthogonalize,
)

# ---------- cross_sectional_neutralize ----------


def _synthetic_panel() -> pl.DataFrame:
    """构造 2 日期 × 3 行业 × 6 样本、带行业均值差的合成面板。"""
    rng = np.random.default_rng(42)
    rows = []
    for d, gv in enumerate(["2026-01-05", "2026-01-06"]):
        for ind, indv in enumerate(["A", "B", "C"]):
            for s in range(6):
                x1 = rng.normal(3, 1) + ind * 2
                x2 = rng.normal(5, 2) + ind * 0.5
                x3 = rng.normal(1, 0.8) - ind * 0.3
                y = 0.8 * x1 - 0.3 * x2 + 0.5 * x3 + ind * 10 + rng.normal(0, 0.5)
                rows.append((gv, indv, f"S{d}{ind}{s}", float(x1), float(x2), float(x3), float(y)))
    return pl.DataFrame(
        rows, schema=["trade_date", "industry", "symbol", "x1", "x2", "x3", "y"], orient="row"
    )


def _numpy_ols_ref(sub: pl.DataFrame, xcols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """numpy 一次性多元 OLS 对照：返回 (系数, 残差)。"""
    ind = sub["industry"].to_numpy()
    dummy_vals = [v for v in ["B", "C"] if v in set(ind.tolist())]
    dummies = np.column_stack([(ind == v).astype(float) for v in dummy_vals])
    design = np.column_stack([np.ones(len(sub)), dummies] + [sub[c].to_numpy() for c in xcols])
    y = sub["y"].to_numpy()
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    return beta[1 + len(dummy_vals) :], y - design @ beta


def test_neutralize_residuals_match_numpy_multiple_ols() -> None:
    res = cross_sectional_neutralize(_synthetic_panel(), "y", "industry", ["x1", "x2", "x3"])

    for gv in ["2026-01-05", "2026-01-06"]:
        sub = res.filter(pl.col("trade_date") == gv)
        _, resid_np = _numpy_ols_ref(sub, ["x1", "x2", "x3"])
        resid_pl = sub["y_neutralized"].to_numpy()
        assert np.abs(resid_pl - resid_np).max() < 1e-9


def test_neutralize_coefficients_match_numpy_multiple_ols() -> None:
    res = cross_sectional_neutralize(_synthetic_panel(), "y", "industry", ["x1", "x2", "x3"])

    for gv in ["2026-01-05", "2026-01-06"]:
        sub = res.filter(pl.col("trade_date") == gv)
        coef_np, _ = _numpy_ols_ref(sub, ["x1", "x2", "x3"])
        coef_pl = np.array([sub["x1_coef"][0], sub["x2_coef"][0], sub["x3_coef"][0]], dtype=float)
        assert np.abs(coef_pl - coef_np).max() < 1e-9


def test_neutralize_residual_uncorrelated_with_industry_and_covariates() -> None:
    res = cross_sectional_neutralize(_synthetic_panel(), "y", "industry", ["x1", "x2"])

    for gv in ["2026-01-05", "2026-01-06"]:
        sub = res.filter(pl.col("trade_date") == gv)
        resid = sub["y_neutralized"].to_numpy()
        # 残差与各协变量（行业内去均值后）不相关（OLS 性质）
        for c in ["x1", "x2"]:
            x = sub[c].to_numpy() - sub[c].to_numpy().mean()
            corr = np.corrcoef(resid, x)[0, 1]
            assert abs(corr) < 1e-9
        # 各行业残差均值 ≈ 0（行业暴露被剥离）
        for indv in ["A", "B", "C"]:
            m = sub.filter(pl.col("industry") == indv)["y_neutralized"].to_numpy().mean()
            assert abs(m) < 1e-9


def test_neutralize_single_covariate_matches_simple_case() -> None:
    # 单协变量 + 行业：系数 = 行业内 cov/var 汇总，残差 = y - b*x 再去行业
    rng = np.random.default_rng(1)
    rows = []
    for gv in ["d1", "d2"]:
        for ind, indv in enumerate(["X", "Y"]):
            for _ in range(5):
                x = rng.normal(2, 1) + ind * 3
                y = 1.5 * x + ind * 7 + rng.normal(0, 0.4)
                rows.append((gv, indv, float(x), float(y)))
    df = pl.DataFrame(rows, schema=["g", "ind", "x", "y"], orient="row")

    res = cross_sectional_neutralize(df, "y", "ind", ["x"], group_col="g")
    for gv in ["d1", "d2"]:
        sub = res.filter(pl.col("g") == gv)
        ind = (sub["ind"] == "Y").to_numpy().astype(float)
        design = np.column_stack([np.ones(len(sub)), ind, sub["x"].to_numpy()])
        y = sub["y"].to_numpy()
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        resid_np = y - design @ beta
        assert abs(sub["x_coef"][0] - beta[2]) < 1e-9
        assert np.abs(sub["y_neutralized"].to_numpy() - resid_np).max() < 1e-9


def test_neutralize_fails_closed_on_missing_industry() -> None:
    df = _synthetic_panel().with_columns(
        pl.when(pl.col("symbol") == "S005")
        .then(None)
        .otherwise(pl.col("industry"))
        .alias("industry")
    )
    res = cross_sectional_neutralize(df, "y", "industry", ["x1"])
    null_row = res.filter(pl.col("symbol") == "S005")["y_neutralized"][0]
    assert null_row is None


def test_neutralize_returns_input_unchanged_when_invalid() -> None:
    frame = pl.DataFrame({"trade_date": ["d1"], "industry": ["A"], "y": [1.0]})
    assert cross_sectional_neutralize(frame, "y", "industry", ["x"]).columns == frame.columns
    assert cross_sectional_neutralize(frame, "y", "missing", ["x"]).columns == frame.columns

    empty = pl.DataFrame(schema={"trade_date": pl.String, "y": pl.Float64})
    assert cross_sectional_neutralize(empty, "y", "industry", ["x"]).is_empty()


def test_neutralize_custom_output_col() -> None:
    res = cross_sectional_neutralize(
        _synthetic_panel(), "y", "industry", ["x1"], output_col="alpha"
    )
    assert "alpha" in res.columns
    assert "y_neutralized" not in res.columns


# ---------- cross_sectional_orthogonalize ----------


def _correlated_panel() -> pl.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for gv in ["d1", "d2"]:
        for _ in range(30):
            f1 = rng.normal(0, 1)
            f2 = 0.9 * f1 + rng.normal(0, 0.3)
            f3 = -0.5 * f1 + 0.2 * f2 + rng.normal(0, 0.4)
            rows.append((gv, f1, f2, f3))
    return pl.DataFrame(rows, schema=["g", "f1", "f2", "f3"], orient="row")


def test_orthogonalize_makes_covariance_identity_per_group() -> None:
    out = cross_sectional_orthogonalize(_correlated_panel(), ["f1", "f2", "f3"], group_col="g")

    assert set(out.columns) == {"g", "f1", "f2", "f3", "f1_orth", "f2_orth", "f3_orth"}
    for d in ["d1", "d2"]:
        sub = out.filter(pl.col("g") == d)
        z = sub.select(pl.col(c + "_orth") for c in ["f1", "f2", "f3"]).to_numpy()
        cov = np.corrcoef(z, rowvar=False)
        assert np.allclose(np.diag(cov), 1.0, atol=1e-9)
        assert np.abs(cov - np.eye(3)).max() < 1e-9


def test_orthogonalize_preserves_row_order() -> None:
    panel = _correlated_panel()
    out = cross_sectional_orthogonalize(panel, ["f1", "f2"], group_col="g")
    assert out["g"].to_list() == panel["g"].to_list()
    assert out["f1"].to_list() == panel["f1"].to_list()


def test_orthogonalize_is_symmetric_no_order_dependence() -> None:
    # 对称正交化对因子顺序无依赖：交换输入列顺序后各因子的正交值不变
    panel = _correlated_panel()
    out_ab = cross_sectional_orthogonalize(panel, ["f1", "f2"], group_col="g")
    out_ba = cross_sectional_orthogonalize(panel, ["f2", "f1"], group_col="g")
    assert np.allclose(out_ab["f1_orth"].to_numpy(), out_ba["f1_orth"].to_numpy(), atol=1e-9)
    assert np.allclose(out_ab["f2_orth"].to_numpy(), out_ba["f2_orth"].to_numpy(), atol=1e-9)


def test_orthogonalize_fails_closed_on_rank_deficient_group() -> None:
    df = pl.DataFrame({"g": ["d1", "d1", "d1"], "f1": [1.0, 2.0, 3.0], "f2": [2.0, 4.0, 6.0]})
    out = cross_sectional_orthogonalize(df, ["f1", "f2"], group_col="g")
    assert out["f1_orth"].to_list() == [None, None, None]
    assert out["f2_orth"].to_list() == [None, None, None]


def test_orthogonalize_fails_closed_on_insufficient_samples() -> None:
    df = pl.DataFrame({"g": ["d1", "d1"], "f1": [1.0, 2.0], "f2": [3.0, 4.0]})
    out = cross_sectional_orthogonalize(df, ["f1", "f2"], group_col="g")
    assert out["f1_orth"].to_list() == [None, None]
    assert out["f2_orth"].to_list() == [None, None]


def test_orthogonalize_returns_input_unchanged_when_invalid() -> None:
    empty = pl.DataFrame(schema={"g": pl.String, "f1": pl.Float64})
    assert cross_sectional_orthogonalize(empty, ["f1"], group_col="g").is_empty()

    frame = pl.DataFrame({"g": ["d1"], "f1": [1.0]})
    assert cross_sectional_orthogonalize(frame, ["missing"], group_col="g").columns == frame.columns
    assert (
        cross_sectional_orthogonalize(frame, ["f1"], group_col="missing").columns == frame.columns
    )
