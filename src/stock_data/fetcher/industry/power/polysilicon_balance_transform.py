"""多晶硅供需平衡转换器。"""

from datetime import UTC, datetime

import polars as pl

POLYSILICON_BALANCE_MONTHLY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "domestic_production_w_tons": pl.Float64,
    "net_imports_w_tons": pl.Float64,
    "total_supply_w_tons": pl.Float64,
    "implied_demand_w_tons": pl.Float64,
    "theoretical_surplus_w_tons": pl.Float64,
    "observed_inventory_w_tons": pl.Float64,
    "observed_inventory_change_w_tons": pl.Float64,
    "inventory_weeks": pl.Float64,
    "reconciliation_residual_w_tons": pl.Float64,
    "supply_yoy": pl.Float64,
    "demand_yoy": pl.Float64,
    "scissors_spread_yoy": pl.Float64,
    "cycle_score": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_polysilicon_balance() -> pl.DataFrame:
    """构造多晶硅供需平衡空事实表骨架。"""
    return pl.DataFrame(schema=POLYSILICON_BALANCE_MONTHLY_SCHEMA)


def build_polysilicon_balance_frame(
    supply_df: pl.DataFrame,
    wafer_df: pl.DataFrame,
    inventory_df: pl.DataFrame | None = None,
    customs_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """构建多晶硅全产业链物理供需平衡、剪刀差与周期评分黄金事实表。"""
    if supply_df.is_empty() or wafer_df.is_empty():
        return empty_polysilicon_balance()

    s_sub = supply_df.select(
        [
            pl.col("report_month"),
            pl.col("trade_date"),
            pl.col("production_w_tons").alias("domestic_production_w_tons"),
            pl.col("production_yoy").alias("supply_yoy"),
            pl.col("release_date"),
            pl.col("data_status"),
        ]
    )
    w_sub = wafer_df.select(
        [
            pl.col("report_month"),
            pl.col("implied_silicon_demand_w_tons").alias("implied_demand_w_tons"),
            pl.col("wafer_output_yoy").alias("demand_yoy"),
        ]
    )

    merged = s_sub.join(w_sub, on="report_month", how="inner")
    if merged.is_empty():
        return empty_polysilicon_balance()

    if customs_df is not None and not customs_df.is_empty():
        if "category_key" in customs_df.columns:
            poly_c = customs_df.filter(
                (pl.col("category_key") == "polysilicon")
                | (pl.col("hs_code").str.starts_with("280461"))
            )
            if not poly_c.is_empty():
                c_agg = poly_c.group_by("report_month").agg(
                    (pl.col("export_volume").sum() / 10000.0).alias("net_imports_w_tons")
                )
                merged = merged.join(c_agg, on="report_month", how="left")
            else:
                merged = merged.with_columns(pl.lit(0.0).alias("net_imports_w_tons"))
        else:
            merged = merged.with_columns(pl.lit(0.0).alias("net_imports_w_tons"))
    else:
        merged = merged.with_columns(pl.lit(0.0).alias("net_imports_w_tons"))

    if inventory_df is not None and not inventory_df.is_empty():
        i_sub = inventory_df.select(
            [
                pl.col("report_month"),
                pl.col("inventory_w_tons").alias("observed_inventory_w_tons"),
                pl.col("inventory_change_w_tons").alias("observed_inventory_change_w_tons"),
            ]
        )
        merged = merged.join(i_sub, on="report_month", how="left")
    else:
        merged = merged.with_columns(
            pl.lit(None).cast(pl.Float64).alias("observed_inventory_w_tons"),
            pl.lit(None).cast(pl.Float64).alias("observed_inventory_change_w_tons"),
        )

    now_iso = datetime.now(UTC).isoformat()
    return (
        merged.with_columns(
            pl.col("net_imports_w_tons").fill_null(0.0),
            (pl.col("domestic_production_w_tons") + pl.col("net_imports_w_tons").fill_null(0.0))
            .round(4)
            .alias("total_supply_w_tons"),
        )
        .with_columns(
            (pl.col("total_supply_w_tons") - pl.col("implied_demand_w_tons"))
            .round(4)
            .alias("theoretical_surplus_w_tons"),
            pl.when(
                pl.col("observed_inventory_w_tons").is_not_null()
                & (pl.col("implied_demand_w_tons") > 0)
            )
            .then(
                (
                    pl.col("observed_inventory_w_tons") / (pl.col("implied_demand_w_tons") / 4.33)
                ).round(2)
            )
            .otherwise(None)
            .alias("inventory_weeks"),
            pl.when(pl.col("demand_yoy").is_not_null() & pl.col("supply_yoy").is_not_null())
            .then((pl.col("demand_yoy") - pl.col("supply_yoy")).round(2))
            .otherwise(None)
            .alias("scissors_spread_yoy"),
        )
        .with_columns(
            pl.when(
                pl.col("theoretical_surplus_w_tons").is_not_null()
                & pl.col("observed_inventory_change_w_tons").is_not_null()
            )
            .then(
                (
                    pl.col("theoretical_surplus_w_tons")
                    - pl.col("observed_inventory_change_w_tons")
                ).round(4)
            )
            .otherwise(None)
            .alias("reconciliation_residual_w_tons"),
            pl.when(pl.col("scissors_spread_yoy").is_not_null())
            .then(
                (
                    pl.col("scissors_spread_yoy") * 0.5
                    - (pl.col("inventory_weeks").fill_null(2.5) - 2.0) * 8.0
                )
                .clip(-100.0, 100.0)
                .round(2)
            )
            .otherwise(0.0)
            .alias("cycle_score"),
            pl.lit("ten_thousand_tons/gw/percent").alias("unit"),
            pl.lit("Derived_Polysilicon_Balance").alias("source"),
            pl.lit("").alias("source_url"),
            pl.lit(now_iso).alias("collected_at"),
        )
        .select(list(POLYSILICON_BALANCE_MONTHLY_SCHEMA.keys()))
        .sort("trade_date")
    )
