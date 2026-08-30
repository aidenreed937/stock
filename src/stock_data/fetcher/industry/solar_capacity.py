"""国家能源局 (NEA) 光伏装机容量 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import SolarCapacityRecord

SOLAR_CAPACITY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "monthly_new_capacity_gw": pl.Float64,
    "cumulative_capacity_gw": pl.Float64,
    "yoy_growth": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_solar_capacity() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=SOLAR_CAPACITY_SCHEMA)


def records_to_solar_frame(records: Sequence[SolarCapacityRecord]) -> pl.DataFrame:
    """将光伏装机容量记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_solar_capacity()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "monthly_new_capacity_gw": [r.monthly_new_capacity_gw for r in records],
        "cumulative_capacity_gw": [r.cumulative_capacity_gw for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "unit": [r.unit or "gw" for r in records],
        "source": [r.source or "NEA" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    return (
        pl.DataFrame(data, schema=SOLAR_CAPACITY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
