r"""历史滚动分位数计算工具。

遵循 ``quant-metric-standards`` 的百分位排名标准：

.. math::

    \\text{Percentile}(x_t) = \\frac{\\text{Rank}_{\\min}(x_t) - 1}{N - 1} \\times 100\\%

其中 :math:`N` 为窗口内有效样本数（去空），:math:`\\text{Rank}_{\\min}` 为升序最小名次。
滚动窗口长度按交易日近似：5 年 = 1,250 日，10 年 = 2,500 日；窗口有效样本不足
窗口长度 80% 或当前值为空时返回缺失，避免过早输出噪声分位。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl

PERCENTILE_SCHEMA_SUFFIXES = ("percentile_5y", "percentile_10y")

#: 5Y / 10Y 滚动窗口交易日数（工程近似，与 quant-metric-standards 一致）
WINDOW_5Y_DAYS = 1_250
WINDOW_10Y_DAYS = 2_500

#: 窗口有效样本覆盖率门槛
MIN_WINDOW_SAMPLE_RATIO = 0.8


def _rolling_rank_min_percentile(
    values: np.ndarray,
    *,
    window: int,
    start_index: int = 0,
) -> np.ndarray:
    """逐行计算滑动窗口内当前值的百分位排名 (0~100)。

    ``values`` 必须按时间升序排列；窗口取当前时刻之前（含当日）的 ``window`` 个
    有效观测。窗口有效样本数不足 ``window * MIN_WINDOW_SAMPLE_RATIO`` 时返回 NaN。

    传入 ``start_index`` 时只计算该下标及之后的行（增量构建语义，历史行返回 NaN），
    避免每次重建对全史重复扫描。
    """
    n = len(values)
    if n < 2:
        return np.full(n, np.nan, dtype=np.float64)
    min_samples = max(1, int(window * MIN_WINDOW_SAMPLE_RATIO))
    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(max(0, start_index), n):
        current = values[i]
        if current is None or (isinstance(current, float) and np.isnan(current)):
            continue
        start = max(0, i - window + 1)
        window_values = values[start : i + 1]
        valid = window_values[~np.isnan(window_values)]
        count = len(valid)
        if count < min_samples:
            continue
        lower_count = int(np.searchsorted(np.sort(valid), current, side="right"))
        if count > 1:
            out[i] = (lower_count - 1) / (count - 1) * 100.0
        else:
            out[i] = 50.0 if not np.isnan(current) else np.nan
    return out


def _to_pl_series(values: np.ndarray, name: str) -> pl.Series:
    """把 numpy 结果转成 Polars Series，并把 NaN 统一为 null（域门禁要求非有限值缺省）。"""
    series = pl.Series(name, values)
    if series.dtype == pl.Float64:
        series = series.fill_nan(None)
    return series


def add_rolling_percentiles(
    frame: pl.DataFrame,
    *,
    key: str,
    date_column: str,
    value_columns: list[str],
    window_5y: int = WINDOW_5Y_DAYS,
    window_10y: int = WINDOW_10Y_DAYS,
    cutoff_date: date | None = None,
) -> pl.DataFrame:
    """按 ``key`` 分组添加 5Y/10Y 滚动分位数列。

    输出列命名为 ``{value_column}_percentile_5y`` 与
    ``{value_column}_percentile_10y``；未在价值列上计算时保持输入列不变。

    传入 ``cutoff_date`` 时只计算该日期及之后行（增量构建语义），该日期之前的
    分位保持缺失（由调用方按已物化 Mart 保存），避免每次全历史重算。
    """
    if frame.is_empty() or not value_columns:
        return frame
    missing = [column for column in value_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"滚动分位数缺少输入列: {missing}")

    frames: list[pl.DataFrame] = []
    percentile_columns = [
        f"{column}{suffix}"
        for column in value_columns
        for suffix in ("_percentile_5y", "_percentile_10y")
    ]
    for _key_value, group in frame.sort([key, date_column]).group_by(key, maintain_order=True):
        group = group.sort(date_column)
        if cutoff_date is not None:
            date_column_values = group.get_column(date_column).to_list()
            target_indices = [
                i
                for i, value in enumerate(date_column_values)
                if value is not None and value >= cutoff_date
            ]
        else:
            target_indices = list(range(group.height))
        if not target_indices:
            frames.append(
                group.with_columns(
                    pl.lit(None, dtype=pl.Float64).alias(column) for column in percentile_columns
                )
            )
            continue
        percentile_series: dict[str, pl.Series] = {}
        compute_start = target_indices[0] if target_indices else 0
        for column in value_columns:
            series = group[column].to_numpy().astype(np.float64, copy=False)
            series = np.where(np.isfinite(series), series, np.nan)
            p5 = _rolling_rank_min_percentile(series, window=window_5y, start_index=compute_start)
            p10 = _rolling_rank_min_percentile(series, window=window_10y, start_index=compute_start)
            percentile_series[f"{column}_percentile_5y"] = _to_pl_series(
                p5, f"{column}_percentile_5y"
            )
            percentile_series[f"{column}_percentile_10y"] = _to_pl_series(
                p10, f"{column}_percentile_10y"
            )
        frames.append(group.with_columns(**percentile_series))

    if not frames:
        return frame
    return pl.concat(frames, how="vertical_relaxed")


def add_rank_percentile(
    frame: pl.DataFrame, *, key: str, date_column: str, value: str
) -> pl.DataFrame:
    """为单一价值列添加基于全网排序的全历史百分位（内部辅助）。

    该函数保留以便未来需要"全样本窗口"分位时复用；当前 Mart 构建优先使用
    :func:`add_rolling_percentiles` 的滚动口径。
    """
    if frame.is_empty() or value not in frame.columns:
        return frame
    valid = frame.filter(pl.col(value).is_not_null())
    if valid.is_empty():
        return frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(f"{value}_percentile"))
    rank = valid.with_columns(pl.col(value).rank("min").over(key).alias("_rank"))
    count = valid.group_by(key).agg(pl.len().alias("_count"))
    result = rank.join(count, on=key, how="left").with_columns(
        pl.when(pl.col("_count") > 1)
        .then((pl.col("_rank") - 1) / (pl.col("_count") - 1) * 100.0)
        .otherwise(None)
        .alias(f"{value}_percentile")
    )
    return result.drop(["_rank", "_count"])


def entity_rolling_window(data: list[float], window: int) -> list[list[float]]:
    """返回按时间升序排列序列的滑动窗口视图（便于调试/测试）。"""
    out: list[list[float]] = []
    n = len(data)
    for i in range(n):
        start = max(0, i - window + 1)
        out.append(data[start : i + 1])
    return out


__all__ = [
    "MIN_WINDOW_SAMPLE_RATIO",
    "PERCENTILE_SCHEMA_SUFFIXES",
    "WINDOW_5Y_DAYS",
    "WINDOW_10Y_DAYS",
    "add_rank_percentile",
    "add_rolling_percentiles",
    "entity_rolling_window",
]
