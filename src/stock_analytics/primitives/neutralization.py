"""截面中性化与正交化原语 (Cross-Sectional Neutralization & Orthogonalization)。

本模块为纯函数、无状态向量化算子，零内部业务依赖，仅依赖 Polars、NumPy 与
SciPy（均为 pyproject 直接/传递依赖）。包含：

- `cross_sectional_neutralize`：行业哑变量 + 连续协变量（如对数流通市值）的
  联合回归残差剥离，产出无行业/市值暴露的纯净 Alpha 因子；
- `cross_sectional_orthogonalize`：截面因子矩阵的 SVD 对称正交化（Löwdin
  白化），使因子两两不相关且方差为 1。

权威依据：
    - 联合中性化等价于 Frisch-Waugh-Lovell (FWL) 定理：目标变量与各协变量
      分别对行业哑变量回归取残差后，再对残差协变量做多元回归，其残差与
      "一次性多元最小二乘" 严格等价 (Frisch 1933 / Waugh & Lovell 1963)；
    - 对称正交化即 SVD 白化 Z = X(X^T X)^(-1/2)，为量化多因子正交化通行做法
      （华泰金工《多因子选股系列之因子正交化》等）。

口径说明：
    - 缺失值 fail-closed：任一样本点缺失行业/协变量/因子时输出缺失，不推断；
    - 截面内样本不足（协变量方差为 0 或样本少于因子数+1）时输出缺失；
    - 正交化按 `group_col`（如 trade_date）逐截面独立进行。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import polars as pl
from scipy import linalg

# SVD 奇异值截断相对容差（低于 S[0] 的此比例视为秩亏）
_SVD_RTOL = 1e-10


def cross_sectional_neutralize(
    df: pl.DataFrame,
    target_col: str,
    industry_col: str,
    covariates: Sequence[str],
    *,
    group_col: str = "trade_date",
    output_col: str | None = None,
) -> pl.DataFrame:
    """对目标因子做行业哑变量 + 连续协变量的联合回归残差剥离。

    公式（FWL 等价的一次性多元回归）:
        y = α_d + Σ_c β_c · X_c + ε
    其中 α_d 为各行业哑变量截距（按 group×industry 组内去均值实现），
    输出残差 ε = y_neutralized（纯净 Alpha）。

    输出列:
        {output_col or target_col}_neutralized: 回归残差（无行业/协变量暴露）；
        {covariate}_coef: 该协变量在原始因子空间中的偏回归系数
            （多协变量时经 Gram-Schmidt 基回代还原，与一次性 OLS 系数一致）。

    Args:
        df: 含 target_col / industry_col / 各 covariates 与 group_col 的面板。
        target_col: 目标因子列名。
        industry_col: 行业分组列名（类别型，如申万一级行业代码）。
        covariates: 连续协变量列名列表（如 ["ln_circ_mv"]）。
        group_col: 截面分组列（通常为 trade_date），每个截面独立回归。
        output_col: 残差输出列名；缺省为 "{target_col}_neutralized"。

    Returns:
        注入残差列与协变量系数列后的输入帧；空/缺列输入原样返回。
    """
    out_name = output_col or f"{target_col}_neutralized"
    if (
        df.is_empty()
        or target_col not in df.columns
        or industry_col not in df.columns
        or group_col not in df.columns
    ):
        return df
    covs = [c for c in covariates if c in df.columns]
    if not covs:
        return df

    g: list[str] = [group_col]
    ig: list[str] = [group_col, industry_col]
    frame = df

    # Step 1: 目标与各协变量对行业哑变量（group×industry 组内去均值）取残差
    t = pl.col(target_col).cast(pl.Float64, strict=False)
    frame = frame.with_columns((t - t.mean().over(ig)).alias("_neu_y"))
    for i, c in enumerate(covs):
        v = pl.col(c).cast(pl.Float64, strict=False)
        frame = frame.with_columns((v - v.mean().over(ig)).alias(f"_neu_c{i}"))

    # Step 2: 残差协变量逐级 Gram-Schmidt 正交化，记录转换系数 a_{ij}
    frame = frame.with_columns(pl.col("_neu_c0").alias("_neu_u0"))
    for i in range(1, len(covs)):
        expr = pl.col(f"_neu_c{i}")
        for j in range(i):
            mask = pl.col(f"_neu_u{j}").is_not_null() & pl.col(f"_neu_c{i}").is_not_null()
            uj = pl.when(mask).then(pl.col(f"_neu_u{j}")).otherwise(None)
            ci = pl.when(mask).then(pl.col(f"_neu_c{i}")).otherwise(None)
            cov_ji = pl.cov(uj, ci).over(g)
            var_j = pl.col(f"_neu_u{j}").var().over(g)
            a_ij = pl.when(var_j > 0).then(cov_ji / var_j).otherwise(None)
            expr = expr - a_ij * pl.col(f"_neu_u{j}")
            frame = frame.with_columns(a_ij.alias(f"_neu_a{i}_{j}"))
        frame = frame.with_columns(expr.alias(f"_neu_u{i}"))

    # Step 3: 目标残差对正交基回归，得基系数 beta_i（正交基内一元系数即多元系数）
    for i in range(len(covs)):
        mask = pl.col("_neu_y").is_not_null() & pl.col(f"_neu_u{i}").is_not_null()
        yv = pl.when(mask).then(pl.col("_neu_y")).otherwise(None)
        uv = pl.when(mask).then(pl.col(f"_neu_u{i}")).otherwise(None)
        cov_i = pl.cov(yv, uv).over(g)
        var_i = pl.col(f"_neu_u{i}").var().over(g)
        beta_i = pl.when(var_i > 0).then(cov_i / var_i).otherwise(None)
        frame = frame.with_columns(beta_i.alias(f"_neu_beta{i}"))

    # Step 4: 回代还原原始协变量空间系数 b（倒序迭代）
    # 推导: u_j = c_j - Σ_{l<j} a_{jl} u_l，故 y = Σ beta_i u_i = Σ b_i c_i
    #      b_{k-1} = beta_{k-1};  b_i = beta_i - Σ_{j>i} a_{ji}·b_j
    for i in reversed(range(len(covs))):
        expr = pl.col(f"_neu_beta{i}")
        for j in range(i + 1, len(covs)):
            expr = expr - pl.col(f"_neu_a{j}_{i}") * pl.col(f"_neu_b{j}")
        frame = frame.with_columns(expr.alias(f"_neu_b{i}"))

    # Step 5: 组装输出；行业缺失行残差置空（fail-closed）
    resid = pl.col("_neu_y")
    for i in range(len(covs)):
        resid = resid - pl.col(f"_neu_beta{i}") * pl.col(f"_neu_u{i}")
    final_exprs = [
        pl.when(pl.col(industry_col).is_not_null()).then(resid).otherwise(None).alias(out_name)
    ]
    for i, c in enumerate(covs):
        final_exprs.append(pl.col(f"_neu_b{i}").alias(f"{c}_coef"))
    frame = frame.with_columns(final_exprs)

    drop_cols = ["_neu_y"] + [f"_neu_c{i}" for i in range(len(covs))]
    drop_cols += [f"_neu_u{i}" for i in range(len(covs))]
    drop_cols += [f"_neu_a{i}_{j}" for i in range(len(covs)) for j in range(i)]
    drop_cols += [f"_neu_beta{i}" for i in range(len(covs))]
    drop_cols += [f"_neu_b{i}" for i in range(len(covs))]
    return frame.drop(drop_cols)


def cross_sectional_orthogonalize(
    df: pl.DataFrame,
    columns: Sequence[str],
    *,
    group_col: str = "trade_date",
    output_suffix: str = "_orth",
) -> pl.DataFrame:
    """对截面因子矩阵做 SVD 对称正交化（Löwdin 白化）。

    公式（逐 group_col 截面）:
        X 为中心化因子矩阵（剔除任一因子缺失的样本行）；
        X = U·S·V^T (thin SVD)；
        Z = U·V^T = X·(X^T X)^(-1/2)
    满足 Z^T Z = I（截面内因子两两不相关且方差为 1），无顺序依赖。

    Args:
        df: 含各因子列与 group_col 的面板。
        columns: 待正交化的因子列名列表。
        group_col: 截面分组列（通常为 trade_date）。
        output_suffix: 输出列后缀，输出列名为 "{col}{output_suffix}"。

    Returns:
        注入正交化列后的输入帧（保持原行序）；空/缺列输入原样返回；
        截面样本不足（<因子数+1）或矩阵秩亏时该截面输出缺失（fail-closed）。
    """
    if df.is_empty() or group_col not in df.columns:
        return df
    valid = [c for c in columns if c in df.columns]
    if not valid:
        return df

    frame = df.with_row_index("__row_idx")
    out_frames = []
    for gv in frame[group_col].unique().to_list():
        sub = frame.filter(pl.col(group_col) == gv)
        out_frames.append(_orthogonalize_group(sub, valid, output_suffix))
    result = pl.concat(out_frames)
    return result.sort("__row_idx").drop("__row_idx")


def _orthogonalize_group(
    sub: pl.DataFrame, columns: Sequence[str], output_suffix: str
) -> pl.DataFrame:
    """对单个截面对因子矩阵做对称正交化并注入输出列。"""
    n = sub.height
    mat = sub.select(pl.col(c).cast(pl.Float64, strict=False) for c in columns).to_numpy()
    k = mat.shape[1]
    out: dict[str, list[float | None]] = {f"{c}{output_suffix}": [None] * n for c in columns}

    valid_idx = np.where(~np.isnan(mat).any(axis=1))[0]
    if valid_idx.size >= k + 1:
        x_center = mat[valid_idx] - mat[valid_idx].mean(axis=0)
        u, s, vt = linalg.svd(x_center, full_matrices=False, lapack_driver="gesdd")
        full_rank = s.size > 0 and s[-1] > _SVD_RTOL * s[0]
        if full_rank:
            z = u @ vt
            for j, col in enumerate(columns):
                vals: list[float | None] = [None] * n
                for pos, row in enumerate(valid_idx):
                    vals[row] = float(z[pos, j])
                out[f"{col}{output_suffix}"] = vals
    return sub.with_columns(pl.Series(name, vals) for name, vals in out.items())


__all__ = [
    "cross_sectional_neutralize",
    "cross_sectional_orthogonalize",
]
