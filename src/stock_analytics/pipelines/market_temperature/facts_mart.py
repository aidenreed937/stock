"""市场温度计与 FeatureStore / Analytics Mart 的指标事实转换器。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.primitives.rules import growth, percentile_rank, rolling_zscore

if TYPE_CHECKING:
    from collections.abc import Iterable

    from stock_reporting.interpretation.market_temperature.config import MetricInputConfig

# 温度计配置 metric_id -> market_daily 宽表列名（仅收录配置实际使用的指标）
_MARKET_DAILY_COLUMN_MAP: dict[str, str] = {
    "return_20d": "return_20d",
    "rsi_14d": "rsi_14d",
    "ma_bias_20d": "ma_bias_20d",
    "advance_share": "advance_ratio",
    "above_ma20_share": "above_ma20_ratio",
    "above_ma60_share": "above_ma60_ratio",
    "new_high_share_252d": "new_high_252d_ratio",
    "new_low_share_252d": "new_low_252d_ratio",
    "margin_buy_share": "margin_buy_ratio",
    "margin_penetration": "margin_penetration",
    "market_turnover_rate": "market_turnover_rate",
    "main_money_net_inflow_share": "main_net_inflow_ratio",
}
_MONEYFLOW_CUM_WINDOW = 20
MARKET_DAILY_FACT_COLUMNS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            "trade_date",
            "total_turnover",
            "main_net_inflow",
            "margin_balance",
            *_MARKET_DAILY_COLUMN_MAP.values(),
        )
    )
)


def _latest_non_null_date(filtered: pl.DataFrame, column: str) -> date | None:
    if column not in filtered.columns:
        return None
    latest = filtered.filter(pl.col(column).is_not_null()).select("trade_date").tail(1)
    return latest["trade_date"][0] if not latest.is_empty() else None


def _calc_percentile_metric(filtered: pl.DataFrame, metric_id: str) -> tuple[float, date] | None:
    col_map = {
        "market_amount_percentile_1250d": "market_turnover_rate",
        "turnover_rate_percentile_1250d": "market_turnover_rate",
        "margin_penetration_percentile_1250d": "margin_penetration",
    }
    col = col_map.get(metric_id)
    if col and col in filtered.columns:
        metric_date = _latest_non_null_date(filtered, col)
        value = percentile_rank(filtered[col].tail(1250), 1250)
        if value is not None and metric_date is not None:
            return value, metric_date
    return None


def _latest_rule_value(filtered: pl.DataFrame, expr: pl.Expr) -> tuple[float, date] | None:
    """应用规则表达式并取最近一个非空观测。"""
    frame = filtered.with_columns(expr.alias("_value")).filter(pl.col("_value").is_not_null())
    if frame.is_empty():
        return None
    latest = frame.tail(1)
    return float(latest["_value"][0]), latest["trade_date"][0]


def _calc_zscore_or_growth(filtered: pl.DataFrame, metric_id: str) -> tuple[float, date] | None:
    if metric_id == "margin_buy_share_zscore_60d" and "margin_buy_ratio" in filtered.columns:
        return _latest_rule_value(filtered, rolling_zscore("margin_buy_ratio", 60))
    if metric_id in {"margin_balance_growth_20d", "margin_balance_growth_60d"}:
        window = 20 if metric_id.endswith("20d") else 60
        if "margin_balance" in filtered.columns:
            return _latest_rule_value(filtered, growth("margin_balance", window))
    return None


def _calc_moneyflow_cumulative_share(
    filtered: pl.DataFrame,
) -> tuple[float, date, date, date] | None:
    required = {"trade_date", "total_turnover", "main_net_inflow"}
    if not required.issubset(filtered.columns):
        return None
    window = (
        filtered.select("trade_date", "total_turnover", "main_net_inflow")
        .drop_nulls()
        .tail(_MONEYFLOW_CUM_WINDOW)
    )
    if window.height < _MONEYFLOW_CUM_WINDOW:
        return None
    total_turnover = float(window["total_turnover"].sum())
    if total_turnover <= 0:
        return None
    main_net_inflow = float(window["main_net_inflow"].sum())
    return (
        main_net_inflow / total_turnover,
        window["trade_date"][-1],
        window["trade_date"][0],
        window["trade_date"][-1],
    )


def _compute_rolling_fact_value(
    filtered: pl.DataFrame, metric_id: str
) -> tuple[float, date] | None:
    """从 market_daily 历史序列计算滚动分位/Z-Score/增长率。"""
    pct = _calc_percentile_metric(filtered, metric_id)
    if pct is not None:
        return pct
    return _calc_zscore_or_growth(filtered, metric_id)


def _mart_fact(
    *,
    dimension: str,
    metric_id: str,
    as_of_date: date,
    value: float,
    metric_date: date,
    sample_size: int,
    note_suffix: str = "",
) -> dict[str, Any]:
    note = f"source=mart.market_daily; metric_date={metric_date.isoformat()}"
    if note_suffix:
        note = f"{note}; {note_suffix}"
    return {
        "fact_id": f"metric.{dimension}.{metric_id}",
        "category": "metric_value",
        "dimension": dimension,
        "data_source": "mart",
        "dataset": "market_daily",
        "as_of_date": as_of_date,
        "window": 0,
        "metric_id": metric_id,
        "value_float": value,
        "value_text": "",
        "unit": "raw",
        "sample_size": sample_size,
        "source": "FeatureStore.market_daily",
        "status": "ok",
        "note": note,
    }


def try_get_market_daily_fact(
    market_daily: pl.DataFrame,
    dimension: str,
    metric: MetricInputConfig,
    as_of_date: date,
    expected_trade_date: date | None = None,
) -> dict[str, Any] | None:
    """尝试直接从已物化的 market_daily 宽表中提取或计算指标事实。"""
    if market_daily.is_empty():
        return None

    filtered = market_daily.filter(pl.col("trade_date") <= as_of_date).sort("trade_date")
    if filtered.is_empty():
        return None

    note_suffix = ""
    if metric.metric_id == "main_money_net_inflow_share_20d_cum":
        cumulative_result = _calc_moneyflow_cumulative_share(filtered)
        if cumulative_result is None:
            return None
        value, metric_date, window_start, window_end = cumulative_result
        note_suffix = (
            f"window_start={window_start.isoformat()}; window_end={window_end.isoformat()}"
        )
    else:
        rolling_result = _compute_rolling_fact_value(filtered, metric.metric_id)
        if rolling_result is not None:
            value, metric_date = rolling_result
        else:
            col_name = _MARKET_DAILY_COLUMN_MAP.get(metric.metric_id)
            if not col_name or col_name not in filtered.columns:
                return None
            latest_row = filtered.filter(pl.col(col_name).is_not_null()).tail(1)
            if latest_row.is_empty():
                return None
            value = float(latest_row[col_name][0])
            metric_date = latest_row["trade_date"][0]

    if expected_trade_date is not None and metric_date != expected_trade_date:
        return None
    return _mart_fact(
        dimension=dimension,
        metric_id=metric.metric_id,
        as_of_date=as_of_date,
        value=float(value),
        metric_date=metric_date,
        sample_size=filtered.height,
        note_suffix=note_suffix,
    )


def parse_date_value(value: object) -> date | None:
    """解析字符串或日期对象为 date。"""
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace("-", "")[:8]
    if len(compact) == 8 and compact.isdigit():
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    if len(text) >= 6 and text[:6].isdigit():
        year = int(text[:4])
        month = int(text[4:6])
        return date(year, month, 1)
    return date.fromisoformat(text[:10])


def date_values(values: Iterable[object]) -> list[date]:
    """批量解析日期列表。"""
    dates: list[date] = []
    for value in values:
        parsed = parse_date_value(value)
        if parsed is not None:
            dates.append(parsed)
    return dates
