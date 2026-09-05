"""芯片交期先导指标的 RAW/Curated 转换器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.semiconductor.models import ChipLeadTimeRecord
from stock_data.fetcher.industry.semiconductor.schemas import (
    CHIP_LEAD_TIME_RAW_SCHEMA,
    CHIP_LEAD_TIME_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)


def empty_raw_chip_lead_time() -> pl.DataFrame:
    """构造芯片交期先导指标 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=CHIP_LEAD_TIME_RAW_SCHEMA)


def records_to_raw_chip_lead_time_frame(
    records: Sequence[ChipLeadTimeRecord],
) -> pl.DataFrame:
    """将芯片交期记录转换为源端字段/字符串值优先的 RAW Polars DataFrame。"""
    if not records:
        return empty_raw_chip_lead_time()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "lead_time_raw": [r.lead_time_raw for r in records],
        "sku_details_raw": [r.sku_details_raw for r in records],
        "source": [r.source or "Susquehanna/Distributor" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }

    return require_raw_release_dates(
        (
            pl.DataFrame(data, schema=CHIP_LEAD_TIME_RAW_SCHEMA)
            .unique(subset=["report_month"], keep="last")
            .sort("trade_date")
        ),
        "chip_lead_time",
    )


def empty_chip_lead_time() -> pl.DataFrame:
    """构造芯片交期先导指标空事实表骨架。"""
    return pl.DataFrame(schema=CHIP_LEAD_TIME_SCHEMA)


def records_to_chip_lead_time_frame(
    records: Sequence[ChipLeadTimeRecord],
) -> pl.DataFrame:
    """将芯片交期记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_chip_lead_time()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "avg_lead_time_weeks": [r.avg_lead_time_weeks for r in records],
        "mcu_lead_time_weeks": [r.mcu_lead_time_weeks for r in records],
        "analog_lead_time_weeks": [r.analog_lead_time_weeks for r in records],
        "discrete_lead_time_weeks": [r.discrete_lead_time_weeks for r in records],
        "compute_lead_time_weeks": [r.compute_lead_time_weeks for r in records],
        "lead_time_yoy_weeks": [r.lead_time_yoy_weeks for r in records],
        "lead_time_mom_weeks": [r.lead_time_mom_weeks for r in records],
        "lead_time_status": [r.lead_time_status for r in records],
        "unit": [r.unit or "weeks" for r in records],
        "source": [r.source or "Susquehanna/Distributor" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    df = (
        pl.DataFrame(data, schema=CHIP_LEAD_TIME_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    if len(df) > 1:
        family = (
            pl.when(pl.col("source").str.contains("Mouser"))
            .then(pl.lit("mouser"))
            .otherwise(pl.lit("susquehanna"))
            .alias("_source_family")
        )
        df = df.with_columns(family)
        avg = pl.col("avg_lead_time_weeks")
        same_family_1 = pl.col("_source_family") == pl.col("_source_family").shift(1)
        same_family_12 = pl.col("_source_family") == pl.col("_source_family").shift(12)
        df = df.with_columns(
            pl.when(same_family_1)
            .then((avg - avg.shift(1)).round(2))
            .otherwise(None)
            .alias("lead_time_mom_weeks"),
            pl.when(same_family_12)
            .then((avg - avg.shift(12)).round(2))
            .otherwise(None)
            .alias("lead_time_yoy_weeks"),
        ).drop("_source_family")
    return df
