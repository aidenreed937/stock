"""工程机械行业月度产销与小松开工小时数 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import ConstructionMachineryRecord

CONSTRUCTION_MACHINERY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "excavator_total_units": pl.Float64,
    "excavator_domestic_units": pl.Float64,
    "excavator_export_units": pl.Float64,
    "komatsu_hours_china": pl.Float64,
    "komatsu_hours_yoy": pl.Float64,
    "export_ratio": pl.Float64,
    "excavator_total_3mma": pl.Float64,
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


def empty_construction_machinery() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=CONSTRUCTION_MACHINERY_SCHEMA)


def records_to_machinery_frame(records: Sequence[ConstructionMachineryRecord]) -> pl.DataFrame:
    """将工程机械记录转换为强类型 Polars DataFrame，并自动计算 3MMA、出口占比与同比/环比。"""
    if not records:
        return empty_construction_machinery()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "excavator_total_units": [r.excavator_total_units for r in records],
        "excavator_domestic_units": [r.excavator_domestic_units for r in records],
        "excavator_export_units": [r.excavator_export_units for r in records],
        "komatsu_hours_china": [r.komatsu_hours_china for r in records],
        "komatsu_hours_yoy": [r.komatsu_hours_yoy for r in records],
        "export_ratio": [r.export_ratio for r in records],
        "excavator_total_3mma": [r.excavator_total_3mma for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "yoy_growth_3mma": [r.yoy_growth_3mma for r in records],
        "mom_growth_3mma": [r.mom_growth_3mma for r in records],
        "unit": [r.unit or "units/hours" for r in records],
        "source": [r.source or "CCMA/Komatsu" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    df = (
        pl.DataFrame(data, schema=CONSTRUCTION_MACHINERY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )

    # 自动补全出口占比 (export / total)
    if df["export_ratio"].null_count() == len(df):
        df = df.with_columns(
            (
                pl.when(pl.col("excavator_total_units") > 0)
                .then(pl.col("excavator_export_units") / pl.col("excavator_total_units"))
                .otherwise(0.0)
            ).alias("export_ratio")
        )

    # 自动补全 3MMA 平滑总销量
    if df["excavator_total_3mma"].null_count() == len(df):
        df = df.with_columns(
            pl.col("excavator_total_units")
            .rolling_mean(window_size=3, min_samples=1)
            .alias("excavator_total_3mma")
        )

    # 衍生同比与环比斜率
    if df["yoy_growth"].null_count() == len(df):
        df = df.with_columns(
            (
                pl.col("excavator_total_units") / pl.col("excavator_total_units").shift(12) - 1.0
            ).alias("yoy_growth")
        )

    if df["yoy_growth_3mma"].null_count() == len(df):
        df = df.with_columns(
            (pl.col("excavator_total_3mma") / pl.col("excavator_total_3mma").shift(12) - 1.0).alias(
                "yoy_growth_3mma"
            ),
            (pl.col("excavator_total_3mma") / pl.col("excavator_total_3mma").shift(1) - 1.0).alias(
                "mom_growth_3mma"
            ),
        )

    return df
