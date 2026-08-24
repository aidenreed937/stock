"""横截面因子工程与统计回归原语 (Cross-Sectional Primitives)。

本模块为纯函数、无状态向量化算子，零内部业务依赖，仅依赖 Polars 与标准库。
包含截面去极值 (MAD Winsorize)、截面/行业中性化 Z-Score、截面等分箱
(Quantile Bucket) 与无状态截面一元 OLS 回归等横截面预处理算子。

权威依据：
    - MAD 去极值基于 Hampel (1974) 稳健统计与 A 股量化因子预处理通行做法，
      以中位数 ± n * 1.4826 * MAD 作为上下限裁剪极端值；
    - 截面 OLS 为一元线性回归闭式解 (slope = Cov(x,y)/Var(x))，
      残差与 R^2 按最小二乘标准定义。
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

# MAD 与正态标准差的一致性系数 (1 / Phi^{-1}(3/4) ≈ 1.4826)，用于稳健去极值
_MAD_CONSISTENCY = 1.4826


def mad_winsorize(
    df: pl.DataFrame,
    columns: Sequence[str],
    n: float = 3.0,
    *,
    group_by: str | None = None,
    output_suffix: str = "_winsorized",
) -> pl.DataFrame:
    """按截面中位数绝对偏差 (MAD) 去极值，将极端值裁剪到稳健上下限。

    公式: median = Median(x); MAD = Median(|x - median|)
          lower = median - n * 1.4826 * MAD; upper = median + n * 1.4826 * MAD
          x_winsorized = clip(x, lower, upper)

    group_by 传入分组列（如行业）时在各组内独立去极值；
    MAD 为 0（组内样本过少或取值恒定时）保持原值，缺失值透传。
    """
    if df.is_empty():
        return df
    valid_cols = [col for col in columns if col in df.columns]
    if not valid_cols:
        return df

    group = pl.col(group_by) if group_by else pl.lit(1)
    exprs = []
    for col in valid_cols:
        value = pl.col(col).cast(pl.Float64, strict=False)
        median = value.median().over(group)
        abs_dev = (value - median).abs()
        mad = abs_dev.median().over(group)
        sigma = mad * _MAD_CONSISTENCY
        lower = median - n * sigma
        upper = median + n * sigma
        winsorized = pl.when(mad > 0).then(value.clip(lower, upper)).otherwise(value)
        exprs.append(winsorized.alias(f"{col}{output_suffix}"))
    return df.with_columns(exprs)


def cross_sectional_zscore(
    df: pl.DataFrame,
    columns: Sequence[str],
    *,
    group_by: str | None = None,
    output_suffix: str = "_cs_zscore",
) -> pl.DataFrame:
    """计算因子列的横截面标准化 Z-Score（可选行业/分组中性化）。

    公式: z = (x - Mean(x)) / Std(x)，样本标准差 (ddof=1)，与 rolling_zscore 口径一致。
    group_by 传入分组列（如行业）时在各组内独立标准化，实现行业中性化；
    组内标准差为 0 或样本不足 2 时输出缺失，缺失值透传。
    """
    if df.is_empty():
        return df
    valid_cols = [col for col in columns if col in df.columns]
    if not valid_cols:
        return df

    group = pl.col(group_by) if group_by else pl.lit(1)
    exprs = []
    for col in valid_cols:
        value = pl.col(col).cast(pl.Float64, strict=False)
        mean = value.mean().over(group)
        std = value.std().over(group)
        zscore = pl.when(std > 0).then((value - mean) / std).otherwise(None)
        exprs.append(zscore.alias(f"{col}{output_suffix}"))
    return df.with_columns(exprs)


def quantile_bucket(
    df: pl.DataFrame,
    column: str,
    n_bins: int = 10,
    *,
    group_by: str | None = None,
    output: str | None = None,
) -> pl.DataFrame:
    """将单列因子按截面等频分箱映射到 1..n_bins 的分位数打分。

    公式: bucket = clip(floor((Rank_min(x) - 1) / N * n_bins) + 1, 1, n_bins)
    基于最小名次排名，重复值共享同一名次与分箱，缺失值透传；
    group_by 传入分组列时在各组内独立分箱。
    """
    if df.is_empty() or column not in df.columns:
        return df
    if n_bins < 1:
        raise ValueError("n_bins must be positive")

    group = pl.col(group_by) if group_by else pl.lit(1)
    value = pl.col(column).cast(pl.Float64, strict=False)
    rank = value.rank("min").over(group)
    n_valid = value.count().over(group)
    bucket_expr = (
        pl.when(value.is_not_null() & (n_valid >= 1))
        .then((((rank - 1) * n_bins / n_valid).floor() + 1.0).cast(pl.Int64).clip(1, n_bins))
        .otherwise(None)
    )
    return df.with_columns(bucket_expr.alias(output or f"{column}_bucket_{n_bins}"))


def _ols_columns(x_col: str, y_col: str, group: pl.Expr, name: str) -> list[pl.Expr]:
    """构造截面一元 OLS 的 5 个输出表达式（含列名别名）。

    仅使用 (x, y) 同时非空的样本对拟合，保证均值、方差、协方差与残差
    统计口径一致；组内有效样本不足 2 或自变量方差为 0 时整组输出缺失。
    """
    x = pl.col(x_col).cast(pl.Float64, strict=False)
    y = pl.col(y_col).cast(pl.Float64, strict=False)
    x_valid = pl.when(x.is_not_null() & y.is_not_null()).then(x).otherwise(None)
    y_valid = pl.when(y.is_not_null() & x.is_not_null()).then(y).otherwise(None)

    n_valid = (x.is_not_null() & y.is_not_null()).cast(pl.Int64).sum().over(group)
    x_mean = x_valid.mean().over(group)
    y_mean = y_valid.mean().over(group)
    var_x = x_valid.var().over(group)
    slope = (
        pl.when((n_valid >= 2) & (var_x > 0))
        .then(pl.cov(x_valid, y_valid).over(group) / var_x)
        .otherwise(None)
    )
    intercept = pl.when((n_valid >= 2) & (var_x > 0)).then(y_mean - slope * x_mean).otherwise(None)
    fitted = (
        pl.when(intercept.is_not_null() & x.is_not_null())
        .then(intercept + slope * x)
        .otherwise(None)
    )
    residual = pl.when(fitted.is_not_null() & y.is_not_null()).then(y - fitted).otherwise(None)
    ss_res = (residual**2).sum().over(group)
    ss_tot = ((y_valid - y_mean) ** 2).sum().over(group)
    r2 = (
        pl.when((n_valid >= 2) & (var_x > 0) & (ss_tot > 0))
        .then(1.0 - ss_res / ss_tot)
        .otherwise(None)
    )

    return [
        slope.alias(f"{name}_slope"),
        intercept.alias(f"{name}_intercept"),
        fitted.alias(f"{name}_fitted"),
        residual.alias(f"{name}_residual"),
        r2.alias(f"{name}_r2"),
    ]


def cross_sectional_ols(
    df: pl.DataFrame,
    x_col: str,
    y_col: str,
    output_prefix: str | None = None,
    *,
    group_by: str | None = None,
) -> pl.DataFrame:
    """拟合无状态截面一元线性回归，输出斜率、截距、拟合值、残差与 R^2。

    公式: slope = Cov(x, y) / Var(x); intercept = Mean(y) - slope * Mean(x)
          fitted = intercept + slope * x; residual = y - fitted
          R^2 = 1 - Sum(residual^2) / Sum((y - Mean(y))^2)

    输出列: {prefix}_slope / _intercept / _fitted / _residual / _r2，
    默认 prefix 为 "{y_col}_on_{x_col}"。group_by 传入分组列时按组独立拟合。
    """
    if df.is_empty() or x_col not in df.columns or y_col not in df.columns:
        return df

    name = output_prefix or f"{y_col}_on_{x_col}"
    group = pl.col(group_by) if group_by else pl.lit(1)
    return df.with_columns(_ols_columns(x_col, y_col, group, name))


__all__ = [
    "cross_sectional_ols",
    "cross_sectional_zscore",
    "mad_winsorize",
    "quantile_bucket",
]
