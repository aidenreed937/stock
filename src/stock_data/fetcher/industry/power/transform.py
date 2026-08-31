"""国家能源局 (NEA) 光伏装机容量 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import (
    SolarCapacityRecord,
    SolarPriceChainRecord,
)

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
    if df["yoy_growth"].null_count() > 0 and "cumulative_capacity_gw" in df.columns:
        df = df.with_columns(
            pl.when(pl.col("yoy_growth").is_null())
            .then(
                pl.col("cumulative_capacity_gw") / pl.col("cumulative_capacity_gw").shift(12) - 1.0
            )
            .otherwise(pl.col("yoy_growth"))
            .alias("yoy_growth")
        )
    return df


SOLAR_PRICE_CHAIN_SCHEMA = {
    "report_date": pl.String,
    "trade_date": pl.Date,
    "polysilicon_price_cny_kg": pl.Float64,
    "wafer_price_cny_piece": pl.Float64,
    "cell_price_cny_watt": pl.Float64,
    "module_price_cny_watt": pl.Float64,
    "module_price_yoy": pl.Float64,
    "module_price_mom": pl.Float64,
    "price_cycle_stage": pl.String,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_solar_price_chain() -> pl.DataFrame:
    """构造光伏产业链价格空事实表骨架。"""
    return pl.DataFrame(schema=SOLAR_PRICE_CHAIN_SCHEMA)


def records_to_solar_price_chain_frame(
    records: Sequence[SolarPriceChainRecord],
) -> pl.DataFrame:
    """将光伏价格链条记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_solar_price_chain()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_date": [r.report_date for r in records],
        "trade_date": [r.trade_date for r in records],
        "polysilicon_price_cny_kg": [r.polysilicon_price_cny_kg for r in records],
        "wafer_price_cny_piece": [r.wafer_price_cny_piece for r in records],
        "cell_price_cny_watt": [r.cell_price_cny_watt for r in records],
        "module_price_cny_watt": [r.module_price_cny_watt for r in records],
        "module_price_yoy": [r.module_price_yoy for r in records],
        "module_price_mom": [r.module_price_mom for r in records],
        "price_cycle_stage": [r.price_cycle_stage or "bottom_rebound" for r in records],
        "unit": [r.unit or "cny_per_unit" for r in records],
        "source": [r.source or "PVInfoLink/SMM" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=SOLAR_PRICE_CHAIN_SCHEMA)
        .unique(subset=["report_date"], keep="last")
        .sort("trade_date")
    )
