"""市场温度计外部环境派生工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from stock_analytics.pipelines.market_temperature.derived_helpers import (
    _metric_row,
    _percentile_metric_row,
)

if TYPE_CHECKING:
    from datetime import date


_EXTERNAL_RETURN_WINDOW = 20
_EXTERNAL_COMPONENT_IDS = (
    "macro_sp500_20d_return_temperature",
    "macro_nasdaq_20d_return_temperature",
    "macro_vix_temperature",
    "macro_usd_index_20d_change_temperature",
    "macro_us_10y_temperature",
    "macro_copper_20d_return_temperature",
)
_EXTERNAL_PRESSURE_COMPONENTS = {
    "macro_safe_haven_pressure_temperature": (
        ("macro_gold_20d_return_pressure", False),
        ("macro_vix_temperature", True),
        ("macro_sp500_20d_return_temperature", True),
        ("macro_nasdaq_20d_return_temperature", True),
    ),
    "macro_inflation_pressure_temperature": (
        ("macro_oil_20d_return_pressure", False),
        ("macro_us_10y_temperature", True),
        ("macro_fred_cpi_yoy_temperature", True),
    ),
    "macro_demand_pressure_temperature": (
        ("macro_copper_20d_return_temperature", True),
        ("macro_oil_20d_return_pressure", True),
        ("macro_sp500_20d_return_temperature", True),
        ("macro_nasdaq_20d_return_temperature", True),
    ),
}
_EXTERNAL_PRESSURE_NOTES = {
    "macro_safe_haven_pressure_temperature": (
        "避险压力=黄金上涨、VIX升温、美股下跌压力可用子项等权平均"
    ),
    "macro_inflation_pressure_temperature": (
        "通胀压力=原油上涨、美债收益率上行、美国CPI压力可用子项等权平均"
    ),
    "macro_demand_pressure_temperature": "需求压力=铜、原油、美股走弱压力可用子项等权平均",
}


def _return_percentile_metric_row(
    frame: pl.DataFrame,
    symbol: str,
    metric_id: str,
    as_of_date: date,
    *,
    inverse: bool = False,
    note: str,
) -> dict[str, Any]:
    return_frame = _return_frame(frame, symbol, _EXTERNAL_RETURN_WINDOW)
    row = _percentile_metric_row(
        return_frame,
        metric_id,
        "_return",
        as_of_date,
        inverse=inverse,
        note=note,
    )
    if row["status"] != "ok":
        row["note"] = f"{note}; symbol={symbol}; 本地数据不足或缺失"
    return row


def _return_frame(frame: pl.DataFrame, symbol: str, window: int) -> pl.DataFrame:
    if frame.is_empty() or not {"symbol", "trade_date", "close"}.issubset(frame.columns):
        return pl.DataFrame()
    return (
        frame.filter(pl.col("symbol") == symbol)
        .select(
            "trade_date",
            pl.col("close").cast(pl.Float64, strict=False).alias("_close"),
        )
        .drop_nulls()
        .filter(pl.col("_close") > 0)
        .sort("trade_date")
        .with_columns((pl.col("_close") / pl.col("_close").shift(window) - 1.0).alias("_return"))
        .select("trade_date", "_return")
    )


def _fred_symbol_frame(frame: pl.DataFrame, symbol: str) -> pl.DataFrame:
    if frame.is_empty() or not {"symbol", "trade_date"}.issubset(frame.columns):
        return pl.DataFrame()
    if "value" in frame.columns:
        source_col = "value"
    elif "close" in frame.columns:
        source_col = "close"
    else:
        source_col = ""
    if not source_col:
        return pl.DataFrame()
    return (
        frame.filter(pl.col("symbol") == symbol)
        .select(
            "trade_date",
            pl.col(source_col).cast(pl.Float64, strict=False).alias("_value"),
        )
        .drop_nulls()
        .sort("trade_date")
    )


def _fred_yoy_frame(frame: pl.DataFrame, symbol: str, periods: int) -> pl.DataFrame:
    data = _fred_symbol_frame(frame, symbol)
    if data.is_empty():
        return pl.DataFrame()
    return (
        data.with_columns(pl.col("_value").shift(periods).alias("_prev_value"))
        .with_columns(
            pl.when(pl.col("_prev_value") > 0)
            .then(pl.col("_value") / pl.col("_prev_value") - 1.0)
            .otherwise(None)
            .alias("_yoy")
        )
        .select("trade_date", "_yoy")
    )


def _external_environment_row(rows: list[dict[str, Any]], as_of_date: date) -> dict[str, Any]:
    component_rows = [row for row in rows if row["metric_id"] in _EXTERNAL_COMPONENT_IDS]
    values = [
        float(row["value_float"])
        for row in component_rows
        if row["status"] == "ok" and row["value_float"] is not None
    ]
    missing = [str(row["metric_id"]) for row in component_rows if row["status"] != "ok"]
    note = "外部环境子温度=美股/VIX/美元/美债/铜可用子项等权平均"
    if missing:
        note = f"{note}; missing={','.join(missing)}"
    return _metric_row(
        "macro_liquidity",
        "macro_external_environment_temperature",
        as_of_date,
        sum(values) / len(values) if values else None,
        sample_size=len(values),
        note=note,
    )


def _external_pressure_rows(rows: list[dict[str, Any]], as_of_date: date) -> list[dict[str, Any]]:
    pressure_rows = [
        _external_pressure_component_row(metric_id, rows, as_of_date)
        for metric_id in _EXTERNAL_PRESSURE_COMPONENTS
    ]
    pressure_rows.append(_external_pressure_total_row(pressure_rows, as_of_date))
    return pressure_rows


def _external_pressure_component_row(
    metric_id: str,
    rows: list[dict[str, Any]],
    as_of_date: date,
) -> dict[str, Any]:
    rows_by_metric = {str(row["metric_id"]): row for row in rows}
    values: list[float] = []
    missing: list[str] = []
    for component_id, invert in _EXTERNAL_PRESSURE_COMPONENTS[metric_id]:
        value = _pressure_component_value(rows_by_metric.get(component_id), invert=invert)
        if value is None:
            missing.append(component_id)
        else:
            values.append(value)
    note = _EXTERNAL_PRESSURE_NOTES[metric_id]
    if missing:
        note = f"{note}; missing={','.join(missing)}"
    return _metric_row(
        "macro_liquidity",
        metric_id,
        as_of_date,
        sum(values) / len(values) if values else None,
        sample_size=len(values),
        note=note,
    )


def _external_pressure_total_row(
    pressure_rows: list[dict[str, Any]],
    as_of_date: date,
) -> dict[str, Any]:
    values = [
        float(row["value_float"])
        for row in pressure_rows
        if row["status"] == "ok" and row["value_float"] is not None
    ]
    missing = [str(row["metric_id"]) for row in pressure_rows if row["status"] != "ok"]
    note = "总体外部压力=避险、通胀、需求三类压力可用子项最大值；仅作风险提示，不进入综合温度"
    if missing:
        note = f"{note}; missing={','.join(missing)}"
    return _metric_row(
        "macro_liquidity",
        "macro_external_pressure_temperature",
        as_of_date,
        max(values) if values else None,
        sample_size=len(values),
        note=note,
    )


def _pressure_component_value(row: dict[str, Any] | None, *, invert: bool) -> float | None:
    if row is None or row.get("status") != "ok" or row.get("value_float") is None:
        return None
    value = float(row["value_float"])
    return 100.0 - value if invert else value
