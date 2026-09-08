"""新能源汽车月度产销 RAW/Curated 转换器。"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.automotive.models import NevMonthlyRecord
from stock_data.fetcher.industry.automotive.schemas import (
    NEV_MONTHLY_RAW_SCHEMA,
    NEV_MONTHLY_SCHEMA,
)


def _raw_text(raw_value: str | None, value: object = None) -> str | None:
    if raw_value is not None and str(raw_value).strip():
        return str(raw_value)
    if value is None:
        return None
    return str(value)


def _raw_number(raw_value: str | None, fallback: float | None) -> float | None:
    if raw_value is not None and str(raw_value).strip():
        match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(raw_value).replace(",", ""))
        if match is not None:
            try:
                return float(match.group(0))
            except ValueError:
                pass
    return fallback


def _raw_ratio(raw_value: str | None, fallback: float | None) -> float | None:
    parsed = _raw_number(raw_value, fallback)
    if parsed is None:
        return None
    if raw_value is not None and "%" in str(raw_value):
        return round(parsed / 100.0, 4)
    return round(parsed, 4)


def empty_raw_nev_monthly() -> pl.DataFrame:
    """构造新能源汽车月度 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=NEV_MONTHLY_RAW_SCHEMA)


def records_to_raw_nev_frame(records: Sequence[NevMonthlyRecord]) -> pl.DataFrame:
    """将记录转换为保留源端字符串和血缘的 RAW 表。"""
    if not records:
        return empty_raw_nev_monthly()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "wholesale_volume_raw": [
            _raw_text(r.wholesale_volume_raw, r.wholesale_volume_ten_thousand) for r in records
        ],
        "total_volume_raw": [
            _raw_text(r.total_volume_raw, r.total_volume_ten_thousand) for r in records
        ],
        "retail_volume_raw": [
            _raw_text(r.retail_volume_raw, r.retail_volume_ten_thousand) for r in records
        ],
        "export_volume_raw": [
            _raw_text(r.export_volume_raw, r.export_volume_ten_thousand) for r in records
        ],
        "penetration_rate_raw": [
            _raw_text(r.penetration_rate_raw, r.penetration_rate) for r in records
        ],
        "battery_installation_gwh_raw": [
            _raw_text(r.battery_installation_gwh_raw, r.battery_installation_gwh) for r in records
        ],
        "yoy_growth_raw": [_raw_text(r.yoy_growth_raw, r.yoy_growth) for r in records],
        "unit": [r.unit or "ten_thousand_units" for r in records],
        "source": [r.source or "CPCA" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }
    return (
        pl.DataFrame(data, schema=NEV_MONTHLY_RAW_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


def empty_nev_monthly() -> pl.DataFrame:
    """构造新能源汽车月度 Curated 空事实表骨架。"""
    return pl.DataFrame(schema=NEV_MONTHLY_SCHEMA)


def records_to_nev_frame(
    records: Sequence[NevMonthlyRecord],
    existing_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """从 RAW 源字段构建 Curated 表，支持与既有 Curated 缝合以保证全时序 3MMA 与同比连贯。"""
    if not records and (existing_df is None or existing_df.is_empty()):
        return empty_nev_monthly()

    ordered_records = sorted(records, key=lambda record: record.trade_date) if records else []
    now_iso = datetime.now(UTC).isoformat()
    wholesale_values = [
        _raw_number(r.wholesale_volume_raw, r.wholesale_volume_ten_thousand)
        for r in ordered_records
    ]
    total_values = [
        _raw_number(r.total_volume_raw, r.total_volume_ten_thousand) for r in ordered_records
    ]
    penetration_values: list[float | None] = []
    for record, wholesale, total in zip(ordered_records, wholesale_values, total_values):
        value = _raw_ratio(record.penetration_rate_raw, record.penetration_rate)
        if value is None and wholesale is not None and total is not None and total > 0:
            value = round(wholesale / total, 4)
        penetration_values.append(value)

    base_data = {
        "report_month": [r.report_month for r in ordered_records],
        "trade_date": [r.trade_date for r in ordered_records],
        "wholesale_volume_ten_thousand": wholesale_values,
        "wholesale_volume_3mma": [None] * len(ordered_records),
        "retail_volume_ten_thousand": [
            _raw_number(r.retail_volume_raw, r.retail_volume_ten_thousand) for r in ordered_records
        ],
        "export_volume_ten_thousand": [
            _raw_number(r.export_volume_raw, r.export_volume_ten_thousand) for r in ordered_records
        ],
        "penetration_rate": penetration_values,
        "battery_installation_gwh": [
            _raw_number(r.battery_installation_gwh_raw, r.battery_installation_gwh)
            for r in ordered_records
        ],
        "yoy_growth": [_raw_ratio(r.yoy_growth_raw, r.yoy_growth) for r in ordered_records],
        "yoy_growth_3mma": [None] * len(ordered_records),
        "mom_growth_3mma": [None] * len(ordered_records),
        "unit": [r.unit or "ten_thousand_units" for r in ordered_records],
        "source": [r.source or "CPCA" for r in ordered_records],
        "source_url": [r.source_url or "" for r in ordered_records],
        "release_date": [r.release_date for r in ordered_records],
        "data_status": [r.data_status or "actual" for r in ordered_records],
        "collected_at": [r.collected_at or now_iso for r in ordered_records],
    }
    df = (
        pl.DataFrame(base_data, schema=NEV_MONTHLY_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    if existing_df is not None and not existing_df.is_empty():
        base_cols = [
            c
            for c in NEV_MONTHLY_SCHEMA
            if c
            not in ("wholesale_volume_3mma", "yoy_growth", "yoy_growth_3mma", "mom_growth_3mma")
        ]
        existing_base = existing_df.select([c for c in base_cols if c in existing_df.columns])
        new_base = df.select([c for c in base_cols if c in df.columns])
        df = (
            pl.concat([existing_base, new_base], how="diagonal_relaxed")
            .unique(subset=["report_month"], keep="last")
            .sort("trade_date")
        )

    df = df.with_columns(
        pl.col("wholesale_volume_ten_thousand")
        .rolling_mean(window_size=3, min_samples=1)
        .alias("wholesale_volume_3mma")
    ).with_columns(
        (pl.col("wholesale_volume_3mma") / pl.col("wholesale_volume_3mma").shift(12) - 1.0).alias(
            "yoy_growth_3mma"
        ),
        (pl.col("wholesale_volume_3mma") / pl.col("wholesale_volume_3mma").shift(1) - 1.0).alias(
            "mom_growth_3mma"
        ),
        (
            pl.col("wholesale_volume_ten_thousand")
            / pl.col("wholesale_volume_ten_thousand").shift(12)
            - 1.0
        ).alias("yoy_growth"),
    )
    return df.select(list(NEV_MONTHLY_SCHEMA))


__all__ = [
    "NEV_MONTHLY_RAW_SCHEMA",
    "NEV_MONTHLY_SCHEMA",
    "empty_nev_monthly",
    "empty_raw_nev_monthly",
    "records_to_nev_frame",
    "records_to_raw_nev_frame",
]
