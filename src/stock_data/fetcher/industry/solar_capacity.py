"""国家能源局 (NEA) 光伏月度新增装机事实表转换器。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_data.fetcher.industry.models import SolarCapacityRecord

SOLAR_CAPACITY_SCHEMA: dict[str, Any] = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "monthly_new_capacity_gw": pl.Float64,
    "cumulative_capacity_gw": pl.Float64,
    "yoy_growth": pl.Float64,
}


def empty_solar_capacity() -> pl.DataFrame:
    """返回空光伏月度装机 DataFrame。"""
    return pl.DataFrame(schema=SOLAR_CAPACITY_SCHEMA)


def records_to_solar_frame(records: list[SolarCapacityRecord]) -> pl.DataFrame:
    """将光伏装机记录列表转换为标准化的 Polars DataFrame。"""
    if not records:
        return empty_solar_capacity()

    data: dict[str, list[Any]] = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "monthly_new_capacity_gw": [r.monthly_new_capacity_gw for r in records],
        "cumulative_capacity_gw": [r.cumulative_capacity_gw for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
    }
    return (
        pl.DataFrame(data, schema=SOLAR_CAPACITY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
