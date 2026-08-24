"""因子有效性检验原语：分层收益与多空组合分析 (Factor Quantile Primitives)。

本模块为纯函数、无状态向量化算子，零内部业务依赖，仅依赖 Polars 与标准库。
包含分层（Quantile）收益面板统计与多空组合 (Long-Short Spread) 分析，
用于检验因子分层收益的单调性与 Top-Bottom 多空价差。

Rank IC / ICIR 评估见同目录 `factor_evaluation.py`。

权威依据：
    - 分层 (Quantile) 单调性与多空组合检验为因子分层测试通行做法
      （Alphalens、华泰金工《多因子选股系列之因子测试》等）；
    - 多空价差 = Top 组平均前向收益 - Bottom 组平均前向收益，
      为名义收益（不含换仓/费用）口径。

口径说明：
    - 输入面板来自 `quantile_forward_returns`，列含 [group_col, bucket,
      fwd_mean, fwd_median, n]；
    - 缺失值 fail-closed：任一截面/分组样本不足时输出缺失，不推断、不填值；
    - 多空"累计最大回撤"为每日 Top-Bottom 点差的累加序列相对峰值的回撤，
      单位为累计点差（非复利百分比），仅作相对形态参考。
"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.primitives.cross_sectional import quantile_bucket


def quantile_forward_returns(
    df: pl.DataFrame,
    factor_col: str,
    forward_col: str,
    n_bins: int = 5,
    group_col: str = "trade_date",
) -> pl.DataFrame:
    """按截面分组将因子等频分箱，统计各箱前向收益均值/中位数/样本数。

    复用 quantile_bucket 做每日截面分箱，缺失因子或缺失前向收益的行被剔除。

    Args:
        df: 含 factor_col 与 forward_col 的面板。
        factor_col: 因子暴露列名。
        forward_col: 前向收益列名（如 fwd_ret_20d）。
        n_bins: 分箱数（如 5 或 10），小于 1 时抛出 ValueError。
        group_col: 截面分组列（通常为 trade_date）。

    Returns:
        [group_col, bucket, fwd_mean, fwd_median, n] 长表；缺失输入返回同 Schema 空表。
    """
    bucket_name = "_fwd_bucket"
    empty_schema = {
        group_col: pl.String,
        "bucket": pl.Int64,
        "fwd_mean": pl.Float64,
        "fwd_median": pl.Float64,
        "n": pl.Int64,
    }
    if (
        df.is_empty()
        or factor_col not in df.columns
        or forward_col not in df.columns
        or group_col not in df.columns
    ):
        return pl.DataFrame(schema=empty_schema)

    bucketed = quantile_bucket(
        df, factor_col, n_bins=n_bins, group_by=group_col, output=bucket_name
    )
    panel = (
        bucketed.filter(pl.col(bucket_name).is_not_null() & pl.col(forward_col).is_not_null())
        .group_by([group_col, bucket_name])
        .agg(
            fwd_mean=pl.col(forward_col).mean(),
            fwd_median=pl.col(forward_col).median(),
            n=pl.col(forward_col).count(),
        )
        .rename({bucket_name: "bucket"})
    )
    return panel.sort([group_col, "bucket"])


def quantile_summary(
    panel: pl.DataFrame,
    n_bins: int,
    group_col: str = "trade_date",
) -> dict[str, Any]:
    """汇总分层收益面板：各箱均值、单调性、多空组合收益与回撤。

    Args:
        panel: quantile_forward_returns 输出的长表。
        n_bins: 分箱数（top = n_bins, bottom = 1）。
        group_col: 时间列名。

    Returns:
        dict:
            by_bucket: [bucket, n_days, n_stocks, weighted_mean, median_of_means]，
                其中 weighted_mean 以各日样本数加权（等效全样本合并口径）；
            monotonicity_spearman: bucket 序号与加权均值的 Spearman 秩相关（单调性）；
            top_bucket_mean / bottom_bucket_mean: 顶层/底层箱加权均值；
            long_short_mean: 每日多空价差 (Top - Bottom) 的时序均值；
            long_short_series: [group_col, top, bottom, spread, cum_spread, drawdown]，
                drawdown 为累积多空收益相对历史峰值的回撤（非正）；
            long_short_max_drawdown: 累积多空收益的最大回撤（最负值）。
    """
    required = {"bucket", "fwd_mean", "n"}
    if panel.is_empty() or not required.issubset(panel.columns) or n_bins < 1:
        return _empty_quantile_summary(group_col)

    by_bucket = (
        panel.group_by("bucket")
        .agg(
            n_days=pl.col("n").count(),
            n_stocks=pl.col("n").sum(),
            weighted_mean=(pl.col("fwd_mean") * pl.col("n")).sum() / pl.col("n").sum(),
            median_of_means=pl.col("fwd_mean").median(),
        )
        .sort("bucket")
    )

    monotonicity: float | None = None
    if by_bucket.height >= 2:
        value = by_bucket.select(pl.corr("bucket", "weighted_mean", method="spearman")).item()
        if isinstance(value, int | float):
            monotonicity = float(value)

    top_rows = by_bucket.filter(pl.col("bucket") == n_bins)
    bottom_rows = by_bucket.filter(pl.col("bucket") == 1)
    top_bucket_mean: float | None = (
        _to_float(top_rows["weighted_mean"][0]) if top_rows.height == 1 else None
    )
    bottom_bucket_mean: float | None = (
        _to_float(bottom_rows["weighted_mean"][0]) if bottom_rows.height == 1 else None
    )

    top_frame = panel.filter(pl.col("bucket") == n_bins).select(
        group_col, pl.col("fwd_mean").alias("top")
    )
    bottom_frame = panel.filter(pl.col("bucket") == 1).select(
        group_col, pl.col("fwd_mean").alias("bottom")
    )
    long_short_series = top_frame.join(bottom_frame, on=group_col, how="inner").sort(group_col)
    long_short_mean: float | None = None
    long_short_max_drawdown: float | None = None
    if not long_short_series.is_empty():
        long_short_series = long_short_series.with_columns(
            spread=pl.col("top") - pl.col("bottom")
        ).with_columns(cum_spread=pl.col("spread").cum_sum())
        long_short_series = long_short_series.with_columns(
            drawdown=pl.col("cum_spread") - pl.col("cum_spread").cum_max()
        )
        spread_mean = long_short_series["spread"].mean()
        drawdown_min = long_short_series["drawdown"].min()
        long_short_mean = _to_float(spread_mean)
        long_short_max_drawdown = _to_float(drawdown_min)

    return {
        "by_bucket": by_bucket,
        "monotonicity_spearman": monotonicity,
        "top_bucket_mean": top_bucket_mean,
        "bottom_bucket_mean": bottom_bucket_mean,
        "long_short_mean": long_short_mean,
        "long_short_max_drawdown": long_short_max_drawdown,
        "long_short_series": long_short_series,
    }


def _to_float(value: object) -> float | None:
    """将数值标量安全转为 float；非数值（含缺失）返回 None。"""
    if isinstance(value, int | float):
        return float(value)
    return None


def _empty_quantile_summary(group_col: str) -> dict[str, Any]:
    """空输入时的分层汇总兜底结构（fail-closed）。"""
    return {
        "by_bucket": pl.DataFrame(
            schema={
                "bucket": pl.Int64,
                "n_days": pl.Int64,
                "n_stocks": pl.Int64,
                "weighted_mean": pl.Float64,
                "median_of_means": pl.Float64,
            }
        ),
        "monotonicity_spearman": None,
        "top_bucket_mean": None,
        "bottom_bucket_mean": None,
        "long_short_mean": None,
        "long_short_max_drawdown": None,
        "long_short_series": pl.DataFrame(
            schema={
                group_col: pl.String,
                "top": pl.Float64,
                "bottom": pl.Float64,
                "spread": pl.Float64,
                "cum_spread": pl.Float64,
                "drawdown": pl.Float64,
            }
        ),
    }


__all__ = [
    "quantile_forward_returns",
    "quantile_summary",
]
