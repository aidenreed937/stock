"""硅业分会月度事实与光伏供需剪刀差转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.power.models import SiliconWaferMonthlyRecord
from stock_data.fetcher.industry.power.schemas import (
    SILICON_WAFER_MONTHLY_SCHEMA,
    SILICON_WAFER_RAW_SCHEMA,
    SOLAR_SUPPLY_DEMAND_SCHEMA,
)


def _raw_text(raw_value: str | None, value: object = None) -> str | None:
    if raw_value is not None and str(raw_value).strip():
        return str(raw_value)
    if value is None:
        return None
    return str(value)


def _raw_number(raw_value: str | None, fallback: float | None) -> float | None:
    if raw_value is not None and str(raw_value).strip():
        try:
            return float(str(raw_value).replace(",", "").strip())
        except ValueError:
            pass
    return fallback


def _raw_rate_ratio(raw_value: str | None, fallback: float | None) -> float | None:
    """将源端百分数同比/环比转为 Curated 小数比例。"""
    value = _raw_number(raw_value, fallback)
    return round(value / 100.0, 6) if value is not None else None


def _derived_utilization(
    output: float | None,
    capacity: float | None,
    fallback: float | None,
    annualized: bool = False,
) -> float | None:
    if output is None or capacity is None or capacity <= 0:
        return fallback
    numerator = output * 12.0 if annualized else output
    return round(numerator / capacity * 100.0, 2)


def get_silicon_consumption_ratio(year: int) -> float:
    """按年份获取行业平均每 GW 单晶硅片的多晶硅消耗系数。"""
    if year <= 2019:
        return 0.32
    if year <= 2021:
        return 0.27
    if year <= 2023:
        return 0.24
    return 0.205


def empty_raw_silicon_wafer_monthly() -> pl.DataFrame:
    """构造硅业分会主表 RAW 空表骨架。"""
    return pl.DataFrame(schema=SILICON_WAFER_RAW_SCHEMA)


def records_to_raw_silicon_wafer_monthly_frame(
    records: Sequence[SiliconWaferMonthlyRecord],
) -> pl.DataFrame:
    """将硅业分会记录转换为只含源端字段的 RAW 表。"""
    if not records:
        return empty_raw_silicon_wafer_monthly()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "polysilicon_output_w_tons_raw": [
            _raw_text(r.polysilicon_output_w_tons_raw, r.polysilicon_output_w_tons) for r in records
        ],
        "polysilicon_output_yoy_raw": [
            _raw_text(r.polysilicon_output_yoy_raw, r.polysilicon_output_yoy) for r in records
        ],
        "polysilicon_operating_rate_raw": [
            _raw_text(r.polysilicon_operating_rate_raw, r.polysilicon_operating_rate)
            for r in records
        ],
        "wafer_output_gw_raw": [
            _raw_text(r.wafer_output_gw_raw, r.wafer_output_gw) for r in records
        ],
        "wafer_output_yoy_raw": [
            _raw_text(r.wafer_output_yoy_raw, r.wafer_output_yoy) for r in records
        ],
        "wafer_operating_rate_raw": [
            _raw_text(r.wafer_operating_rate_raw, r.wafer_operating_rate) for r in records
        ],
        "polysilicon_inventory_w_tons_raw": [
            _raw_text(r.polysilicon_inventory_w_tons_raw, r.polysilicon_inventory_w_tons)
            for r in records
        ],
        "polysilicon_capacity_annual_w_tons_raw": [
            _raw_text(
                r.polysilicon_capacity_annual_w_tons_raw,
                r.polysilicon_capacity_annual_w_tons,
            )
            for r in records
        ],
        "wafer_capacity_annual_gw_raw": [
            _raw_text(r.wafer_capacity_annual_gw_raw, r.wafer_capacity_annual_gw) for r in records
        ],
        "source": [r.source or "Silicon_Branch_Antaike" for r in records],
        "source_url": [r.source_url or "http://www.silicon.net.cn/" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
        "capacity_raw_content_sha256": [r.capacity_raw_content_sha256 or "" for r in records],
        "capacity_raw_snapshot_path": [r.capacity_raw_snapshot_path or "" for r in records],
    }
    return (
        pl.DataFrame(data, schema=SILICON_WAFER_RAW_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


def empty_silicon_wafer_monthly() -> pl.DataFrame:
    """构造硅业分会多晶硅与硅片月度空事实表骨架。"""
    return pl.DataFrame(schema=SILICON_WAFER_MONTHLY_SCHEMA)


def records_to_silicon_wafer_monthly_frame(
    records: Sequence[SiliconWaferMonthlyRecord],
) -> pl.DataFrame:
    """将硅业分会多晶硅与硅片月度运行记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_silicon_wafer_monthly()

    ordered_records = sorted(records, key=lambda record: record.trade_date)
    polysilicon_outputs = [
        _raw_number(r.polysilicon_output_w_tons_raw, r.polysilicon_output_w_tons)
        for r in ordered_records
    ]
    wafer_outputs = [_raw_number(r.wafer_output_gw_raw, r.wafer_output_gw) for r in ordered_records]
    polysilicon_capacities = [
        _raw_number(
            r.polysilicon_capacity_annual_w_tons_raw,
            r.polysilicon_capacity_annual_w_tons,
        )
        for r in ordered_records
    ]
    wafer_capacities = [
        _raw_number(r.wafer_capacity_annual_gw_raw, r.wafer_capacity_annual_gw)
        for r in ordered_records
    ]
    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in ordered_records],
        "trade_date": [r.trade_date for r in ordered_records],
        "polysilicon_output_w_tons": list(polysilicon_outputs),
        "polysilicon_output_yoy": [
            _raw_rate_ratio(r.polysilicon_output_yoy_raw, r.polysilicon_output_yoy)
            for r in ordered_records
        ],
        "polysilicon_operating_rate": [
            _raw_number(r.polysilicon_operating_rate_raw, r.polysilicon_operating_rate)
            for r in ordered_records
        ],
        "derived_polysilicon_utilization_rate": [
            _derived_utilization(
                polysilicon_outputs[index],
                polysilicon_capacities[index],
                r.derived_polysilicon_utilization_rate,
                annualized=True,
            )
            for index, r in enumerate(ordered_records)
        ],
        "wafer_output_gw": list(wafer_outputs),
        "wafer_output_yoy": [
            _raw_rate_ratio(r.wafer_output_yoy_raw, r.wafer_output_yoy) for r in ordered_records
        ],
        "wafer_operating_rate": [
            _raw_number(r.wafer_operating_rate_raw, r.wafer_operating_rate) for r in ordered_records
        ],
        "derived_wafer_utilization_rate": [
            _derived_utilization(
                wafer_outputs[index],
                wafer_capacities[index],
                r.derived_wafer_utilization_rate,
            )
            for index, r in enumerate(ordered_records)
        ],
        "polysilicon_inventory_w_tons": [
            _raw_number(r.polysilicon_inventory_w_tons_raw, r.polysilicon_inventory_w_tons)
            for r in ordered_records
        ],
        "polysilicon_capacity_annual_w_tons": list(polysilicon_capacities),
        "wafer_capacity_annual_gw": list(wafer_capacities),
        "unit": ["ten_thousand_tons/gw/ratio" for _ in ordered_records],
        "source": [r.source or "Silicon_Branch_Antaike" for r in ordered_records],
        "source_url": [r.source_url or "http://www.silicon.net.cn/" for r in ordered_records],
        "release_date": [r.release_date for r in ordered_records],
        "data_status": [r.data_status or "actual" for r in ordered_records],
        "collected_at": [r.collected_at or now_iso for r in ordered_records],
    }

    return (
        pl.DataFrame(data, schema=SILICON_WAFER_MONTHLY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


def empty_solar_supply_demand() -> pl.DataFrame:
    """构造光伏供需剪刀差空事实表骨架。"""
    return pl.DataFrame(schema=SOLAR_SUPPLY_DEMAND_SCHEMA)


def _derived_collected_at(*frames: pl.DataFrame) -> str:
    """沿用上游事实的最新采集时间，避免无输入变化时制造假更新。"""
    values: list[str] = []
    for frame in frames:
        if "collected_at" in frame.columns:
            values.extend(str(value) for value in frame["collected_at"].drop_nulls().to_list())
    return max(values) if values else datetime.now(UTC).isoformat()


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

    collected_at = _derived_collected_at(cell_df, install_df)
    return (
        merged.with_columns(
            (pl.col("supply_cell_gw") - pl.col("demand_install_gw"))
            .round(4)
            .alias("monthly_surplus_gw"),
            pl.when(pl.col("supply_cell_gw") > 0)
            .then((pl.col("demand_install_gw") / pl.col("supply_cell_gw")).round(4))
            .otherwise(None)
            .alias("domestic_absorption_ratio"),
            pl.when(
                pl.col("demand_install_yoy").is_not_null() & pl.col("supply_cell_yoy").is_not_null()
            )
            # 口径说明：两侧同比均为 Curated 小数比例，剪刀差也保持小数比例。
            .then((pl.col("demand_install_yoy") - pl.col("supply_cell_yoy")).round(4))
            .otherwise(None)
            .alias("scissors_spread_yoy"),
            pl.lit("gw/ratio").alias("unit"),
            pl.lit("Derived_From_NBS_And_NEA").alias("source"),
            pl.lit("").alias("source_url"),
            pl.lit("derived").alias("data_status"),
            pl.lit(collected_at).alias("collected_at"),
        )
        .select(list(SOLAR_SUPPLY_DEMAND_SCHEMA.keys()))
        .sort("trade_date")
    )
