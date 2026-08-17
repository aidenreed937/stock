"""估值分位数、股权风险溢价与收益率曲线原子计算原语。

本模块为纯函数、无状态数学原语，零内部业务依赖，仅依赖 Polars 与标准库。
"""

from __future__ import annotations

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


def calculate_rolling_percentile(
    df: pl.DataFrame,
    metric_cols: tuple[str, ...] = ("pe_ttm", "pb"),
    window_days: int = 1250,
) -> pl.DataFrame:
    """计算指标在过去 N 个交易日 (如 5 年约 1250 日) 滚动窗口内的历史百分位 (0~100)。

    公式: Count(x_i <= x_current) / Window_Size * 100
    """
    if df.is_empty():
        return df

    valid_cols = [c for c in metric_cols if c in df.columns]
    if not valid_cols:
        return df

    has_symbol = "symbol" in df.columns
    exprs = []

    for col in valid_cols:
        col_name = f"{col}_percentile_{window_days}d"
        if has_symbol:
            rolling_min = pl.col(col).rolling_min(window_size=window_days).over("symbol")
            rolling_max = pl.col(col).rolling_max(window_size=window_days).over("symbol")
        else:
            rolling_min = pl.col(col).rolling_min(window_size=window_days)
            rolling_max = pl.col(col).rolling_max(window_size=window_days)

        pct_expr = (
            ((pl.col(col) - rolling_min) / (rolling_max - rolling_min + 1e-8) * 100.0)
            .clip(0.0, 100.0)
            .alias(col_name)
        )
        exprs.append(pct_expr)

    return df.with_columns(exprs)


def calculate_equity_risk_premium(
    df: pl.DataFrame,
    pe_col: str = "pe_ttm",
    bond_yield_col: str = "cn_10y_bond_yield",
) -> pl.DataFrame:
    """计算股权风险溢价 (ERP, Equity Risk Premium)。

    公式: ERP = (1 / PE_TTM) * 100 - 10年期国债收益率(%)
    """
    required = {pe_col, bond_yield_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    earning_yield = (1.0 / (pl.col(pe_col) + 1e-6)) * 100.0
    erp_expr = (earning_yield - pl.col(bond_yield_col)).alias("equity_risk_premium")

    return df.with_columns(erp_expr)


def calculate_yield_curve_slope(
    df: pl.DataFrame,
    long_yield_col: str = "t10y",
    short_yield_col: str = "t2y",
) -> pl.DataFrame:
    """计算国债期限利差与收益率曲线斜率 (如 10Y - 2Y 利差)。"""
    required = {long_yield_col, short_yield_col}
    if df.is_empty() or not required.issubset(df.columns):
        return df

    slope_expr = (pl.col(long_yield_col) - pl.col(short_yield_col)).alias(
        "yield_curve_slope_10y_2y"
    )
    return df.with_columns(slope_expr)


__all__ = [
    "calculate_equity_risk_premium",
    "calculate_index_valuation_summary",
    "calculate_rolling_percentile",
    "calculate_valuation_percentile",
    "calculate_yield_curve_slope",
]
