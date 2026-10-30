"""多晶硅供给、库存与硅片月度事实转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.power.models import (
    PolysiliconInventoryMonthlyRecord,
    PolysiliconSupplyMonthlyRecord,
    PvWaferMonthlyRecord,
)
from stock_data.fetcher.industry.power.schemas import (
    POLYSILICON_INVENTORY_MONTHLY_SCHEMA,
    POLYSILICON_SUPPLY_MONTHLY_SCHEMA,
    PV_WAFER_MONTHLY_SCHEMA,
)
from stock_data.fetcher.industry.power.transforms.silicon import get_silicon_consumption_ratio


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
    ordered_records = sorted(records, key=lambda record: record.trade_date)
    data = {
        "report_month": [r.report_month for r in ordered_records],
        "trade_date": [r.trade_date for r in ordered_records],
        "production_w_tons": [r.production_w_tons for r in ordered_records],
        "production_3mma": [None for _ in ordered_records],
        "production_yoy": [r.production_yoy for r in ordered_records],
        "production_mom": [r.production_mom for r in ordered_records],
        "capacity_annual_w_tons": [r.capacity_annual_w_tons for r in ordered_records],
        "operating_rate": [r.operating_rate for r in ordered_records],
        "derived_utilization_rate": [
            (
                round(r.production_w_tons * 12.0 / r.capacity_annual_w_tons * 100.0, 2)
                if (
                    r.production_w_tons is not None
                    and r.capacity_annual_w_tons is not None
                    and r.capacity_annual_w_tons > 0
                )
                else r.derived_utilization_rate
            )
            for r in ordered_records
        ],
        "unit": ["ten_thousand_tons/ratio" for _ in ordered_records],
        "source": [r.source or "Silicon_Branch_Antaike" for r in ordered_records],
        "source_url": [r.source_url or "" for r in ordered_records],
        "release_date": [r.release_date for r in ordered_records],
        "data_status": [r.data_status or "actual" for r in ordered_records],
        "collected_at": [r.collected_at or now_iso for r in ordered_records],
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
            .then(pl.col("production_w_tons") / pl.col("production_w_tons").shift(12) - 1.0)
            .otherwise(pl.col("production_yoy"))
            .alias("production_yoy")
        )
    if df["production_mom"].null_count() > 0:
        df = df.with_columns(
            pl.when(pl.col("production_mom").is_null())
            .then(pl.col("production_w_tons") / pl.col("production_w_tons").shift(1) - 1.0)
            .otherwise(pl.col("production_mom"))
            .alias("production_mom")
        )
    return df


def empty_polysilicon_inventory() -> pl.DataFrame:
    """构造多晶硅月度库存空事实表骨架。"""
    return pl.DataFrame(schema=POLYSILICON_INVENTORY_MONTHLY_SCHEMA)


def _derive_inventory_weeks_and_status(df: pl.DataFrame) -> pl.DataFrame:
    """按当月隐含硅料需求折算库存周数并分级（口径对齐 polysilicon_balance 表）。

    库存周数 = 期末库存 / (当月隐含需求 / 4.33 周)，与 balance.py 完全同式；
    分级阈值以 balance 周期打分的中性锚 2 周为参照：<2 紧缺 / 2-4 正常 /
    4-8 偏高 / 8-12 过剩 / >=12 严重过剩。
    """
    df = df.with_columns(
        pl.when(
            pl.col("implied_silicon_demand_w_tons").is_not_null()
            & (pl.col("implied_silicon_demand_w_tons") > 0)
        )
        .then(
            (pl.col("inventory_w_tons") / (pl.col("implied_silicon_demand_w_tons") / 4.33)).round(2)
        )
        .otherwise(None)
        .alias("inventory_weeks"),
    )
    return df.with_columns(
        pl.when(pl.col("inventory_weeks") < 2.0)
        .then(pl.lit("tight"))
        .when(pl.col("inventory_weeks") < 4.0)
        .then(pl.lit("normal"))
        .when(pl.col("inventory_weeks") < 8.0)
        .then(pl.lit("elevated"))
        .when(pl.col("inventory_weeks") < 12.0)
        .then(pl.lit("oversupply"))
        .otherwise(pl.lit("severe_oversupply"))
        .alias("inventory_status"),
    )


def records_to_polysilicon_inventory_frame(
    records: Sequence[PolysiliconInventoryMonthlyRecord],
    wafer_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """将多晶硅月度库存记录转换为强类型 Polars DataFrame。

    传入 `wafer_df`（含 `report_month` / `implied_silicon_demand_w_tons`）时
    按当月隐含需求补算 `inventory_weeks` / `inventory_status`，与派生路径口径一致。
    """
    if not records:
        return empty_polysilicon_inventory()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "inventory_w_tons": [r.inventory_w_tons for r in records],
        "inventory_change_w_tons": [r.inventory_change_w_tons for r in records],
        "inventory_weeks": [r.inventory_weeks for r in records],
        "inventory_status": [r.inventory_status for r in records],
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
    if wafer_df is not None and not wafer_df.is_empty():
        df = df.join(
            wafer_df.select(["report_month", "implied_silicon_demand_w_tons"]),
            on="report_month",
            how="left",
        )
        df = _derive_inventory_weeks_and_status(df)
        df = df.select(list(POLYSILICON_INVENTORY_MONTHLY_SCHEMA))
    return df


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
        "unit": ["gw/ten_thousand_tons/ratio" for _ in records],
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
        .then(pl.col("wafer_output_gw") / pl.col("wafer_output_gw").shift(1) - 1.0)
        .otherwise(pl.col("wafer_output_mom"))
        .alias("wafer_output_mom"),
    )
    if df["silicon_consumption_ratio"].null_count() > 0:
        years = [int(str(month).split("-", 1)[0]) for month in df["report_month"].to_list()]
        ratios = [get_silicon_consumption_ratio(year) for year in years]
        df = df.with_columns(
            pl.when(pl.col("silicon_consumption_ratio").is_null())
            .then(pl.Series(ratios, dtype=pl.Float64))
            .otherwise(pl.col("silicon_consumption_ratio"))
            .alias("silicon_consumption_ratio")
        )
    if df["implied_silicon_demand_w_tons"].null_count() > 0:
        df = df.with_columns(
            pl.when(
                pl.col("implied_silicon_demand_w_tons").is_null()
                & pl.col("silicon_consumption_ratio").is_not_null()
            )
            .then((pl.col("wafer_output_gw") * pl.col("silicon_consumption_ratio")).round(4))
            .otherwise(pl.col("implied_silicon_demand_w_tons"))
            .alias("implied_silicon_demand_w_tons")
        )
    if df["wafer_output_yoy"].null_count() > 0:
        df = df.with_columns(
            pl.when(pl.col("wafer_output_yoy").is_null())
            .then(pl.col("wafer_output_gw") / pl.col("wafer_output_gw").shift(12) - 1.0)
            .otherwise(pl.col("wafer_output_yoy"))
            .alias("wafer_output_yoy")
        )
    return df


def build_polysilicon_supply_from_silicon_frame(silicon_df: pl.DataFrame) -> pl.DataFrame:
    """从硅业分会 Curated 主表构建多晶硅供给派生表。"""
    if silicon_df.is_empty():
        return pl.DataFrame(schema=POLYSILICON_SUPPLY_MONTHLY_SCHEMA)
    capacity_column = (
        pl.col("polysilicon_capacity_annual_w_tons")
        if "polysilicon_capacity_annual_w_tons" in silicon_df.columns
        else pl.lit(None, dtype=pl.Float64)
    )
    result = silicon_df.select(
        [
            "report_month",
            "trade_date",
            pl.col("polysilicon_output_w_tons").alias("production_w_tons"),
            pl.col("polysilicon_output_yoy").alias("production_yoy"),
            pl.col("polysilicon_operating_rate").alias("operating_rate"),
            pl.col("derived_polysilicon_utilization_rate").alias("derived_utilization_rate"),
            capacity_column.alias("capacity_annual_w_tons"),
            pl.lit("ten_thousand_tons/ratio").alias("unit"),
            "source",
            "source_url",
            "release_date",
            "data_status",
            "collected_at",
        ]
    ).sort("trade_date")
    return result.with_columns(
        pl.col("production_w_tons")
        .rolling_mean(window_size=3, min_samples=1)
        .alias("production_3mma"),
        (pl.col("production_w_tons") / pl.col("production_w_tons").shift(1) - 1.0).alias(
            "production_mom"
        ),
    ).select(list(POLYSILICON_SUPPLY_MONTHLY_SCHEMA))


def build_polysilicon_inventory_from_silicon_frame(silicon_df: pl.DataFrame) -> pl.DataFrame:
    """从硅业分会 Curated 主表构建多晶硅库存派生表。

    隐含硅料需求按 `wafer_output_gw × 当年耗硅系数` 自包含计算（与
    `build_pv_wafer_from_silicon_frame` 同口径），再补算库存周数与分级状态。
    """
    if silicon_df.is_empty():
        return pl.DataFrame(schema=POLYSILICON_INVENTORY_MONTHLY_SCHEMA)
    result = (
        silicon_df.filter(pl.col("polysilicon_inventory_w_tons").is_not_null())
        .select(
            [
                "report_month",
                "trade_date",
                pl.col("polysilicon_inventory_w_tons").alias("inventory_w_tons"),
                "wafer_output_gw",
                pl.lit("ten_thousand_tons/weeks").alias("unit"),
                "source",
                "source_url",
                "release_date",
                "data_status",
                "collected_at",
            ]
        )
        .sort("trade_date")
    )
    if result.is_empty():
        return pl.DataFrame(schema=POLYSILICON_INVENTORY_MONTHLY_SCHEMA)
    years = [int(str(month).split("-", 1)[0]) for month in result["report_month"].to_list()]
    result = result.with_columns(
        (pl.col("inventory_w_tons") - pl.col("inventory_w_tons").shift(1)).alias(
            "inventory_change_w_tons"
        ),
        pl.Series(
            "implied_silicon_demand_w_tons",
            [
                (
                    round(wafer * get_silicon_consumption_ratio(year), 4)
                    if wafer is not None
                    else None
                )
                for wafer, year in zip(result["wafer_output_gw"].to_list(), years)
            ],
            dtype=pl.Float64,
        ),
    )
    return _derive_inventory_weeks_and_status(result).select(
        list(POLYSILICON_INVENTORY_MONTHLY_SCHEMA)
    )


def build_pv_wafer_from_silicon_frame(silicon_df: pl.DataFrame) -> pl.DataFrame:
    """从硅业分会 Curated 主表构建硅片产出派生表。"""
    if silicon_df.is_empty():
        return pl.DataFrame(schema=PV_WAFER_MONTHLY_SCHEMA)
    result = silicon_df.select(
        [
            "report_month",
            "trade_date",
            "wafer_output_gw",
            "wafer_output_yoy",
            "wafer_operating_rate",
            "derived_wafer_utilization_rate",
            pl.lit("gw/ten_thousand_tons/ratio").alias("unit"),
            "source",
            "source_url",
            "release_date",
            "data_status",
            "collected_at",
        ]
    ).sort("trade_date")
    result = result.with_columns(
        pl.col("wafer_output_gw")
        .rolling_mean(window_size=3, min_samples=1)
        .alias("wafer_output_3mma"),
        (pl.col("wafer_output_gw") / pl.col("wafer_output_gw").shift(1) - 1.0).alias(
            "wafer_output_mom"
        ),
    )
    years = [int(str(month).split("-", 1)[0]) for month in result["report_month"].to_list()]
    result = (
        result.with_columns(
            pl.Series(
                "silicon_consumption_ratio",
                [get_silicon_consumption_ratio(year) for year in years],
                dtype=pl.Float64,
            )
        )
        .with_columns(
            pl.when(
                pl.col("wafer_output_gw").is_not_null()
                & pl.col("silicon_consumption_ratio").is_not_null()
            )
            .then((pl.col("wafer_output_gw") * pl.col("silicon_consumption_ratio")).round(4))
            .otherwise(None)
            .alias("implied_silicon_demand_w_tons")
        )
        .select(list(PV_WAFER_MONTHLY_SCHEMA))
    )
    return result
