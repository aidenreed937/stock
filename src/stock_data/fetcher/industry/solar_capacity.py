"""国家能源局 (NEA) 光伏装机容量 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import SolarCapacityRecord

SOLAR_CAPACITY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "monthly_new_capacity_gw": pl.Float64,
    "monthly_new_capacity_3mma": pl.Float64,
    "cumulative_capacity_gw": pl.Float64,
    "yoy_growth": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
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
        "monthly_new_capacity_3mma": [r.monthly_new_capacity_3mma for r in records],
        "cumulative_capacity_gw": [r.cumulative_capacity_gw for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "yoy_growth_3mma": [r.yoy_growth_3mma for r in records],
        "mom_growth_3mma": [r.mom_growth_3mma for r in records],
        "unit": [r.unit or "gw" for r in records],
        "source": [r.source or "NEA" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=SOLAR_CAPACITY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    # 若记录中未显式传入 3MMA，自动进行滚动平滑与斜率补全
    if df["monthly_new_capacity_3mma"].null_count() == len(df):
        df = df.with_columns(
            pl.col("monthly_new_capacity_gw")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("monthly_new_capacity_3mma")
        ).with_columns(
            (
                pl.col("monthly_new_capacity_3mma") / pl.col("monthly_new_capacity_3mma").shift(12)
                - 1.0
            ).alias("yoy_growth_3mma"),
            (
                pl.col("monthly_new_capacity_3mma") / pl.col("monthly_new_capacity_3mma").shift(1)
                - 1.0
            ).alias("mom_growth_3mma"),
        )
    return df
