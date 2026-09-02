"""国家能源局 (NEA) 光伏装机容量 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import (
    SolarCapacityRecord,
    SolarCellNbsRecord,
    SolarPriceChainRecord,
)
from stock_data.fetcher.industry.power.polysilicon_balance_transform import (
    POLYSILICON_BALANCE_MONTHLY_SCHEMA,
    build_polysilicon_balance_frame,
    empty_polysilicon_balance,
)
from stock_data.fetcher.industry.power.polysilicon_transform import (
    POLYSILICON_INVENTORY_MONTHLY_SCHEMA,
    POLYSILICON_SUPPLY_MONTHLY_SCHEMA,
    PV_WAFER_MONTHLY_SCHEMA,
    empty_polysilicon_inventory,
    empty_polysilicon_supply,
    empty_pv_wafer,
    records_to_polysilicon_inventory_frame,
    records_to_polysilicon_supply_frame,
    records_to_pv_wafer_frame,
)
from stock_data.fetcher.industry.power.silicon_transform import (
    SILICON_WAFER_MONTHLY_SCHEMA,
    SOLAR_SUPPLY_DEMAND_SCHEMA,
    build_solar_supply_demand_frame,
    empty_silicon_wafer_monthly,
    empty_solar_supply_demand,
    get_silicon_consumption_ratio,
    records_to_silicon_wafer_monthly_frame,
)

__all__ = [
    "POLYSILICON_BALANCE_MONTHLY_SCHEMA",
    "POLYSILICON_INVENTORY_MONTHLY_SCHEMA",
    "POLYSILICON_SUPPLY_MONTHLY_SCHEMA",
    "PV_WAFER_MONTHLY_SCHEMA",
    "SILICON_WAFER_MONTHLY_SCHEMA",
    "SOLAR_CAPACITY_SCHEMA",
    "SOLAR_CELL_NBS_SCHEMA",
    "SOLAR_PRICE_CHAIN_SCHEMA",
    "SOLAR_SUPPLY_DEMAND_SCHEMA",
    "build_polysilicon_balance_frame",
    "build_solar_supply_demand_frame",
    "empty_polysilicon_balance",
    "empty_polysilicon_inventory",
    "empty_polysilicon_supply",
    "empty_pv_wafer",
    "empty_silicon_wafer_monthly",
    "empty_solar_capacity",
    "empty_solar_cell_nbs",
    "empty_solar_price_chain",
    "empty_solar_supply_demand",
    "get_silicon_consumption_ratio",
    "records_to_polysilicon_inventory_frame",
    "records_to_polysilicon_supply_frame",
    "records_to_pv_wafer_frame",
    "records_to_silicon_wafer_monthly_frame",
    "records_to_solar_cell_nbs_frame",
    "records_to_solar_frame",
    "records_to_solar_price_chain_frame",
]

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


# --- 国家统计局 (NBS) 太阳能电池 (光伏电池) 月度产量 ---

SOLAR_CELL_NBS_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "output_current": pl.Float64,
    "output_current_3mma": pl.Float64,
    "output_cumulative": pl.Float64,
    "output_yoy": pl.Float64,
    "output_cum_yoy": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_solar_cell_nbs() -> pl.DataFrame:
    """构造 NBS 太阳能电池产量空事实表骨架。"""
    return pl.DataFrame(schema=SOLAR_CELL_NBS_SCHEMA)


def records_to_solar_cell_nbs_frame(records: Sequence[SolarCellNbsRecord]) -> pl.DataFrame:
    """将 NBS 太阳能电池月度产量记录转换为强类型 Polars DataFrame。

    1-2 月合并口径处理（对齐化工 NBS `capacity_utilization_10y`）：当月值缺省时，
    1 月取 2 月累计/2、2 月取 2 月累计/2 填充，保证月度序列连续。
    """
    if not records:
        return empty_solar_cell_nbs()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "output_current": [r.output_current for r in records],
        "output_current_3mma": [r.output_current_3mma for r in records],
        "output_cumulative": [r.output_cumulative for r in records],
        "output_yoy": [r.output_yoy for r in records],
        "output_cum_yoy": [r.output_cum_yoy for r in records],
        "yoy_growth_3mma": [r.yoy_growth_3mma for r in records],
        "mom_growth_3mma": [r.mom_growth_3mma for r in records],
        "unit": [r.unit or "ten_thousand_kw" for r in records],
        "source": [r.source or "NBS" for r in records],
        "source_url": [r.source_url or "https://data.stats.gov.cn/" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=SOLAR_CELL_NBS_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    # 1-2 月合并填充（对齐化工 NBS capacity_utilization_10y）：
    # 2 月当月值 = 2 月累计/2；1 月当月值 = 下一行（2 月）当月值。
    if df["output_current"].null_count() > 0:
        df = (
            df.with_columns(
                pl.when(
                    pl.col("output_current").is_null()
                    & (pl.col("report_month").str.slice(5, 2) == "02")
                )
                .then(pl.col("output_cumulative") / 2.0)
                .otherwise(pl.col("output_current"))
                .alias("_feb_filled")
            )
            .with_columns(
                pl.when(
                    pl.col("output_current").is_null()
                    & (pl.col("report_month").str.slice(5, 2) == "01")
                )
                .then(pl.col("_feb_filled").shift(-1))
                .when(
                    pl.col("output_current").is_null()
                    & (pl.col("report_month").str.slice(5, 2) == "02")
                )
                .then(pl.col("_feb_filled"))
                .otherwise(pl.col("output_current"))
                .alias("output_current")
            )
            .drop("_feb_filled")
        )
    # 若未显式传入 3MMA，自动滚动平滑并派生同比/环比
    if df["output_current_3mma"].null_count() == len(df):
        df = df.with_columns(
            pl.col("output_current")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("output_current_3mma")
        ).with_columns(
            (pl.col("output_current_3mma") / pl.col("output_current_3mma").shift(12) - 1.0).alias(
                "yoy_growth_3mma"
            ),
            (pl.col("output_current_3mma") / pl.col("output_current_3mma").shift(1) - 1.0).alias(
                "mom_growth_3mma"
            ),
        )
    # 同比缺省时由累计同比兜底（若存在）
    if df["output_yoy"].null_count() > 0 and "output_cum_yoy" in df.columns:
        df = df.with_columns(
            pl.when(pl.col("output_yoy").is_null())
            .then(pl.col("output_cum_yoy"))
            .otherwise(pl.col("output_yoy"))
            .alias("output_yoy")
        )
    return df
