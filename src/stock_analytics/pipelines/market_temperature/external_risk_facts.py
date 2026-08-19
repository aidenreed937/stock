"""外盘单日冲击原始事实。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from datetime import date


def raw_external_change_rows(
    index_frame: pl.DataFrame,
    macro_frame: pl.DataFrame,
    as_of_date: date,
) -> list[dict[str, Any]]:
    """从外盘日线生成单日冲击原始事实。"""
    return [
        raw_external_change_metric_row(
            index_frame,
            "^GSPC",
            "macro_sp500_1d_return",
            as_of_date,
            note="标普500 1日收益",
            unit="return",
        ),
        raw_external_change_metric_row(
            index_frame,
            "^IXIC",
            "macro_nasdaq_1d_return",
            as_of_date,
            note="纳斯达克综合指数1日收益",
            unit="return",
        ),
        raw_external_change_metric_row(
            index_frame,
            "^SOX",
            "macro_sox_1d_return",
            as_of_date,
            note="费城半导体指数1日收益",
            unit="return",
        ),
        raw_external_change_metric_row(
            macro_frame,
            "^VIX",
            "macro_vix_1d_change",
            as_of_date,
            note="VIX 1日相对变化",
            unit="return",
        ),
        raw_external_change_metric_row(
            macro_frame,
            "^TNX",
            "macro_us_10y_1d_change",
            as_of_date,
            note="美债10年期收益率1日变化",
            unit="percentage_point",
            relative=False,
        ),
    ]


def raw_external_change_metric_row(
    frame: pl.DataFrame,
    symbol: str,
    metric_id: str,
    as_of_date: date,
    *,
    note: str,
    unit: str,
    relative: bool = True,
) -> dict[str, Any]:
    """生成单个外盘标的的原始单日变化事实。"""
    change_frame = _return_frame(frame, symbol) if relative else _difference_frame(frame, symbol)
    if change_frame.is_empty():
        return _raw_metric_row(
            "macro_liquidity",
            metric_id,
            as_of_date,
            None,
            unit=unit,
            status="insufficient",
            note=f"{note}; symbol={symbol}; 本地数据不足或缺失",
        )

    latest = (
        change_frame.filter(pl.col("trade_date") <= as_of_date)
        .drop_nulls("_change")
        .sort("trade_date")
    )
    if latest.is_empty():
        return _raw_metric_row(
            "macro_liquidity",
            metric_id,
            as_of_date,
            None,
            unit=unit,
            status="insufficient",
            note=f"{note}; symbol={symbol}; 本地数据不足或缺失",
        )

    latest_date = latest["trade_date"][-1]
    latest_value = float(latest["_change"][-1])
    return _raw_metric_row(
        "macro_liquidity",
        metric_id,
        as_of_date,
        latest_value,
        unit=unit,
        sample_size=1,
        note=f"{note}; symbol={symbol}; latest_date={latest_date}; latest_value={latest_value:.6g}",
    )


def _return_frame(frame: pl.DataFrame, symbol: str) -> pl.DataFrame:
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
        .with_columns((pl.col("_close") / pl.col("_close").shift(1) - 1.0).alias("_change"))
        .select("trade_date", "_change")
    )


def _difference_frame(frame: pl.DataFrame, symbol: str) -> pl.DataFrame:
    if frame.is_empty() or not {"symbol", "trade_date", "close"}.issubset(frame.columns):
        return pl.DataFrame()
    return (
        frame.filter(pl.col("symbol") == symbol)
        .select(
            "trade_date",
            pl.col("close").cast(pl.Float64, strict=False).alias("_close"),
        )
        .drop_nulls()
        .sort("trade_date")
        .with_columns((pl.col("_close") - pl.col("_close").shift(1)).alias("_change"))
        .select("trade_date", "_change")
    )


def _raw_metric_row(
    dimension: str,
    metric_id: str,
    as_of_date: date,
    value: float | None,
    *,
    unit: str,
    sample_size: int | None = None,
    status: str = "ok",
    note: str = "",
) -> dict[str, Any]:
    actual_status = status if value is not None else "insufficient"
    return {
        "fact_id": f"metric.{dimension}.{metric_id}",
        "category": "metric_value",
        "dimension": dimension,
        "data_source": "derived",
        "dataset": "",
        "as_of_date": as_of_date,
        "window": 1,
        "metric_id": metric_id,
        "value_float": float(value) if value is not None else None,
        "value_text": "",
        "unit": unit,
        "sample_size": sample_size,
        "source": "market_temperature.derived",
        "status": actual_status,
        "note": note,
    }
