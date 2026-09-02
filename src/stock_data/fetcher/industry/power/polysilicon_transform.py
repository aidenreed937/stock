"""多晶硅供给、库存与硅片月度事实转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import (
    PolysiliconInventoryMonthlyRecord,
    PolysiliconSupplyMonthlyRecord,
    PvWaferMonthlyRecord,
)
from stock_data.fetcher.industry.power.silicon_transform import get_silicon_consumption_ratio

POLYSILICON_SUPPLY_MONTHLY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "production_w_tons": pl.Float64,
    "production_3mma": pl.Float64,
    "production_yoy": pl.Float64,
    "production_mom": pl.Float64,
    "capacity_annual_w_tons": pl.Float64,
    "operating_rate": pl.Float64,
    "derived_utilization_rate": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_polysilicon_supply() -> pl.DataFrame:
    """构造多晶硅月度供给空事实表骨架。"""
    return pl.DataFrame(schema=POLYSILICON_SUPPLY_MONTHLY_SCHEMA)


def records_to_polysilicon_supply_frame(
    records: Sequence[PolysiliconSupplyMonthlyRecord],
) -> pl.DataFrame:
    """将多晶硅月度供给记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_polysilicon_supply()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "production_w_tons": [r.production_w_tons for r in records],
        "production_3mma": [None for _ in records],
        "production_yoy": [r.production_yoy for r in records],
        "production_mom": [r.production_mom for r in records],
        "capacity_annual_w_tons": [r.capacity_annual_w_tons for r in records],
        "operating_rate": [r.operating_rate for r in records],
        "derived_utilization_rate": [r.derived_utilization_rate for r in records],
        "unit": [r.unit or "ten_thousand_tons" for r in records],
        "source": [r.source or "Silicon_Branch_Antaike" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=POLYSILICON_SUPPLY_MONTHLY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    df = df.with_columns(
        pl.col("production_w_tons")
        .rolling_mean(window_size=3, min_samples=1)
        .alias("production_3mma")
    )
    if df["production_yoy"].null_count() > 0:
        df = df.with_columns(
            pl.when(pl.col("production_yoy").is_null())
            .then(
                (pl.col("production_w_tons") / pl.col("production_w_tons").shift(12) - 1.0) * 100.0
            )
            .otherwise(pl.col("production_yoy"))
            .alias("production_yoy")
        )
    if df["production_mom"].null_count() > 0:
        df = df.with_columns(
            pl.when(pl.col("production_mom").is_null())
            .then(
                (pl.col("production_w_tons") / pl.col("production_w_tons").shift(1) - 1.0) * 100.0
            )
            .otherwise(pl.col("production_mom"))
            .alias("production_mom")
        )
    return df


POLYSILICON_INVENTORY_MONTHLY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "inventory_w_tons": pl.Float64,
    "inventory_change_w_tons": pl.Float64,
    "inventory_weeks": pl.Float64,
    "inventory_status": pl.String,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_polysilicon_inventory() -> pl.DataFrame:
    """构造多晶硅月度库存空事实表骨架。"""
    return pl.DataFrame(schema=POLYSILICON_INVENTORY_MONTHLY_SCHEMA)


def records_to_polysilicon_inventory_frame(
    records: Sequence[PolysiliconInventoryMonthlyRecord],
) -> pl.DataFrame:
    """将多晶硅月度库存记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_polysilicon_inventory()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "inventory_w_tons": [r.inventory_w_tons for r in records],
        "inventory_change_w_tons": [r.inventory_change_w_tons for r in records],
        "inventory_weeks": [r.inventory_weeks for r in records],
        "inventory_status": [r.inventory_status or "normal" for r in records],
        "unit": [r.unit or "ten_thousand_tons/weeks" for r in records],
        "source": [r.source or "Silicon_Branch_Antaike" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=POLYSILICON_INVENTORY_MONTHLY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    if df["inventory_change_w_tons"].null_count() > 0:
        df = df.with_columns(
            pl.when(pl.col("inventory_change_w_tons").is_null())
            .then(pl.col("inventory_w_tons") - pl.col("inventory_w_tons").shift(1))
            .otherwise(pl.col("inventory_change_w_tons"))
            .alias("inventory_change_w_tons")
        )
    return df


PV_WAFER_MONTHLY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "wafer_output_gw": pl.Float64,
    "wafer_output_3mma": pl.Float64,
    "wafer_output_yoy": pl.Float64,
    "wafer_output_mom": pl.Float64,
    "wafer_operating_rate": pl.Float64,
    "derived_wafer_utilization_rate": pl.Float64,
    "silicon_consumption_ratio": pl.Float64,
    "implied_silicon_demand_w_tons": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_pv_wafer() -> pl.DataFrame:
    """构造硅片月度产出空事实表骨架。"""
    return pl.DataFrame(schema=PV_WAFER_MONTHLY_SCHEMA)


def records_to_pv_wafer_frame(records: Sequence[PvWaferMonthlyRecord]) -> pl.DataFrame:
    """将硅片月度产出记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_pv_wafer()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "wafer_output_gw": [r.wafer_output_gw for r in records],
        "wafer_output_3mma": [None for _ in records],
        "wafer_output_yoy": [r.wafer_output_yoy for r in records],
        "wafer_output_mom": [None for _ in records],
        "wafer_operating_rate": [r.wafer_operating_rate for r in records],
        "derived_wafer_utilization_rate": [r.derived_wafer_utilization_rate for r in records],
        "silicon_consumption_ratio": [r.silicon_consumption_ratio for r in records],
        "implied_silicon_demand_w_tons": [r.implied_silicon_demand_w_tons for r in records],
        "unit": [r.unit or "gw/ten_thousand_tons" for r in records],
        "source": [r.source or "Silicon_Branch_Antaike" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=PV_WAFER_MONTHLY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    df = df.with_columns(
        pl.col("wafer_output_gw")
        .rolling_mean(window_size=3, min_samples=1)
        .alias("wafer_output_3mma"),
        pl.when(pl.col("wafer_output_mom").is_null())
        .then((pl.col("wafer_output_gw") / pl.col("wafer_output_gw").shift(1) - 1.0) * 100.0)
        .otherwise(pl.col("wafer_output_mom"))
        .alias("wafer_output_mom"),
    )
    if df["silicon_consumption_ratio"].null_count() > 0:
        years = [int(m.split("-")[0]) for m in df["report_month"].to_list()]
        ratios = [get_silicon_consumption_ratio(y) for y in years]
        df = df.with_columns(
            pl.when(pl.col("silicon_consumption_ratio").is_null())
            .then(pl.Series(ratios, dtype=pl.Float64))
            .otherwise(pl.col("silicon_consumption_ratio"))
            .alias("silicon_consumption_ratio")
        )
    if df["implied_silicon_demand_w_tons"].null_count() > 0:
        df = df.with_columns(
            pl.when(pl.col("implied_silicon_demand_w_tons").is_null())
            .then((pl.col("wafer_output_gw") * pl.col("silicon_consumption_ratio")).round(4))
            .otherwise(pl.col("implied_silicon_demand_w_tons"))
            .alias("implied_silicon_demand_w_tons")
        )
    if df["wafer_output_yoy"].null_count() > 0:
        df = df.with_columns(
            pl.when(pl.col("wafer_output_yoy").is_null())
            .then((pl.col("wafer_output_gw") / pl.col("wafer_output_gw").shift(12) - 1.0) * 100.0)
            .otherwise(pl.col("wafer_output_yoy"))
            .alias("wafer_output_yoy")
        )
    return df
