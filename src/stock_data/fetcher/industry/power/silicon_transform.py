"""硅业分会月度事实与光伏供需剪刀差转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import SiliconWaferMonthlyRecord

SILICON_WAFER_MONTHLY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "polysilicon_output_w_tons": pl.Float64,
    "polysilicon_output_yoy": pl.Float64,
    "polysilicon_operating_rate": pl.Float64,
    "derived_polysilicon_utilization_rate": pl.Float64,
    "wafer_output_gw": pl.Float64,
    "wafer_output_yoy": pl.Float64,
    "wafer_operating_rate": pl.Float64,
    "derived_wafer_utilization_rate": pl.Float64,
    "polysilicon_inventory_w_tons": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_silicon_wafer_monthly() -> pl.DataFrame:
    """构造硅业分会多晶硅与硅片月度空事实表骨架。"""
    return pl.DataFrame(schema=SILICON_WAFER_MONTHLY_SCHEMA)


def records_to_silicon_wafer_monthly_frame(
    records: Sequence[SiliconWaferMonthlyRecord],
) -> pl.DataFrame:
    """将硅业分会多晶硅与硅片月度运行记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_silicon_wafer_monthly()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "polysilicon_output_w_tons": [r.polysilicon_output_w_tons for r in records],
        "polysilicon_output_yoy": [r.polysilicon_output_yoy for r in records],
        "polysilicon_operating_rate": [r.polysilicon_operating_rate for r in records],
        "derived_polysilicon_utilization_rate": [
            r.derived_polysilicon_utilization_rate for r in records
        ],
        "wafer_output_gw": [r.wafer_output_gw for r in records],
        "wafer_output_yoy": [r.wafer_output_yoy for r in records],
        "wafer_operating_rate": [r.wafer_operating_rate for r in records],
        "derived_wafer_utilization_rate": [r.derived_wafer_utilization_rate for r in records],
        "polysilicon_inventory_w_tons": [r.polysilicon_inventory_w_tons for r in records],
        "unit": [r.unit or "ten_thousand_tons_and_gw" for r in records],
        "source": [r.source or "Silicon_Branch_Antaike" for r in records],
        "source_url": [r.source_url or "http://www.silicon.net.cn/" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=SILICON_WAFER_MONTHLY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


SOLAR_SUPPLY_DEMAND_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "supply_cell_gw": pl.Float64,
    "demand_install_gw": pl.Float64,
    "monthly_surplus_gw": pl.Float64,
    "domestic_absorption_ratio": pl.Float64,
    "supply_cell_yoy": pl.Float64,
    "demand_install_yoy": pl.Float64,
    "scissors_spread_yoy": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_solar_supply_demand() -> pl.DataFrame:
    """构造光伏供需剪刀差空事实表骨架。"""
    return pl.DataFrame(schema=SOLAR_SUPPLY_DEMAND_SCHEMA)


def build_solar_supply_demand_frame(
    cell_df: pl.DataFrame,
    install_df: pl.DataFrame,
) -> pl.DataFrame:
    """基于电池片产量与装机量构建光伏供需剪刀差黄金事实表。"""
    if cell_df.is_empty() or install_df.is_empty():
        return empty_solar_supply_demand()

    c_sub = cell_df.select(
        [
            pl.col("report_month"),
            (pl.col("output_current") / 100.0).alias("supply_cell_gw"),
            pl.col("output_yoy").alias("supply_cell_yoy"),
        ]
    )
    i_sub = install_df.select(
        [
            pl.col("report_month"),
            pl.col("trade_date"),
            pl.col("monthly_new_capacity_gw").alias("demand_install_gw"),
            pl.col("yoy_growth").alias("demand_install_yoy"),
            pl.col("release_date"),
        ]
    )

    merged = i_sub.join(c_sub, on="report_month", how="inner")
    if merged.is_empty():
        return empty_solar_supply_demand()

    now_iso = datetime.now(UTC).isoformat()
    return (
        merged.with_columns(
            (pl.col("supply_cell_gw") - pl.col("demand_install_gw"))
            .round(4)
            .alias("monthly_surplus_gw"),
            pl.when(pl.col("supply_cell_gw") > 0)
            .then((pl.col("demand_install_gw") / pl.col("supply_cell_gw") * 100.0).round(2))
            .otherwise(None)
            .alias("domestic_absorption_ratio"),
            pl.when(
                pl.col("demand_install_yoy").is_not_null() & pl.col("supply_cell_yoy").is_not_null()
            )
            .then((pl.col("demand_install_yoy") - pl.col("supply_cell_yoy")).round(2))
            .otherwise(None)
            .alias("scissors_spread_yoy"),
            pl.lit("gw_and_percent").alias("unit"),
            pl.lit("Derived_From_NBS_And_NEA").alias("source"),
            pl.lit("").alias("source_url"),
            pl.lit("actual").alias("data_status"),
            pl.lit(now_iso).alias("collected_at"),
        )
        .select(list(SOLAR_SUPPLY_DEMAND_SCHEMA.keys()))
        .sort("trade_date")
    )


def get_silicon_consumption_ratio(year: int) -> float:
    """按年份获取行业平均每 GW 单晶硅片多晶硅消耗系数。"""
    if year <= 2019:
        return 0.32
    if year <= 2021:
        return 0.27
    if year <= 2023:
        return 0.24
    return 0.205
