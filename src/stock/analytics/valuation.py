"""指数与股票历史估值分位数与定投决策计算器。"""

from datetime import date, datetime
from typing import Any

import polars as pl

from stock.utils.logger import logger


def _evaluate_percentile_zone(percentile_rank: float) -> tuple[str, str, float]:
    """根据分位数判定估值区间与定投建议乘数。"""
    if percentile_rank < 10.0:
        return "EXTREME_LOW", "极度低估", 2.0
    if percentile_rank < 30.0:
        return "LOW", "低估", 1.5
    if percentile_rank <= 70.0:
        return "NEUTRAL", "合理", 1.0
    if percentile_rank <= 90.0:
        return "HIGH", "高估", 0.5
    return "EXTREME_HIGH", "极度高估", 0.0


def _preprocess_valuation_df(
    df: pl.DataFrame, metric_col: str, window_years: int | None
) -> pl.DataFrame:
    """预处理数据帧，提取合规时间序列。"""
    if df.is_empty() or metric_col not in df.columns or "trade_date" not in df.columns:
        return pl.DataFrame()

    target_df = df.drop_nulls(subset=["trade_date", metric_col])
    if target_df.is_empty():
        return pl.DataFrame()

    if target_df["trade_date"].dtype == pl.String:
        target_df = target_df.with_columns(
            pl.col("trade_date").str.to_date("%Y-%m-%d").alias("trade_date")
        )

    target_df = target_df.sort("trade_date")

    if window_years is not None and window_years > 0:
        latest_date = target_df["trade_date"].max()
        if isinstance(latest_date, date | datetime):
            start_year = latest_date.year - window_years
            target_df = target_df.filter(pl.col("trade_date").dt.year() >= start_year)

    return target_df


def calculate_valuation_percentile(
    df: pl.DataFrame,
    metric_col: str = "close",
    window_years: int | None = 10,
) -> dict[str, Any]:
    """计算指定指标在历史时间窗口内的百分位与定投决策建议。

    Args:
        df: 包含历史数据的 DataFrame，必须包含 trade_date 列与指定的 metric_col 列。
        metric_col: 估值指标列名 (如 "close", "pe", "pe_ttm", "pb", "dv_ratio" 等)。
        window_years: 历史窗口年数 (如 5 或 10，若为 None 则使用全历史数据)。

    Returns:
        dict[str, Any]: 估值分位结果字典。
    """
    target_df = _preprocess_valuation_df(df, metric_col, window_years)
    if target_df.is_empty():
        logger.warning(f"估值计算未能获取合规数据 [列: {metric_col}]")
        return {}

    total_count = len(target_df)
    series = target_df[metric_col]
    current_val = float(series[-1])
    min_val = float(series.min())  # type: ignore[arg-type]
    max_val = float(series.max())  # type: ignore[arg-type]
    mean_val = float(series.mean())  # type: ignore[arg-type]
    median_val = float(series.median())  # type: ignore[arg-type]

    is_inverse = metric_col.lower() in {"dv_ratio", "dividend_yield", "yield"}

    if is_inverse:
        count_above = float(series.filter(series >= current_val).len())
        percentile_rank = (count_above / total_count) * 100.0
    else:
        count_below = float(series.filter(series <= current_val).len())
        percentile_rank = (count_below / total_count) * 100.0

    zone, zone_cn, multiplier = _evaluate_percentile_zone(percentile_rank)

    return {
        "metric": metric_col,
        "window_years": window_years,
        "sample_size": total_count,
        "current_value": current_val,
        "min_value": min_val,
        "max_value": max_val,
        "mean_value": mean_val,
        "median_value": median_val,
        "percentile_rank": round(percentile_rank, 2),
        "zone": zone,
        "zone_cn": zone_cn,
        "multiplier": multiplier,
        "is_inverse": is_inverse,
    }


def calculate_index_valuation_summary(
    df: pl.DataFrame,
    symbol: str = "",
    window_years: int | None = 10,
) -> dict[str, Any]:
    """生成指数多维估值诊断与定投建议总结。"""
    if df.is_empty():
        return {}

    metrics_to_check = ["pe_ttm", "pe", "pb", "dv_ratio", "close"]
    available_metrics = [m for m in metrics_to_check if m in df.columns]

    if not available_metrics:
        return {}

    evaluations: dict[str, Any] = {}
    for m in available_metrics:
        res = calculate_valuation_percentile(df, metric_col=m, window_years=window_years)
        if res:
            evaluations[m] = res

    if evaluations:
        primary_metric = available_metrics[0]
        primary_eval = evaluations[primary_metric]
        suggested_multiplier = primary_eval["multiplier"]
        overall_zone = primary_eval["zone_cn"]
    else:
        suggested_multiplier = 1.0
        overall_zone = "未知"

    return {
        "symbol": symbol,
        "evaluations": evaluations,
        "overall_zone": overall_zone,
        "suggested_multiplier": suggested_multiplier,
    }
