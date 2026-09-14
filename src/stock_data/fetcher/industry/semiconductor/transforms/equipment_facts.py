"""半导体设备出货额的 RAW 与 Curated 转换器。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import parse_month_string
from stock_data.fetcher.industry.semiconductor.models import SemiconductorEquipmentRecord
from stock_data.fetcher.industry.semiconductor.schemas import (
    SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA,
    SEMICONDUCTOR_EQUIPMENT_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)


def empty_raw_semiconductor_equipment() -> pl.DataFrame:
    """构造半导体设备出货 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA)


def records_to_raw_semiconductor_equipment_frame(
    records: Sequence[SemiconductorEquipmentRecord],
) -> pl.DataFrame:
    """将半导体设备出货记录转换为源端字段/字符串值优先的 RAW Polars DataFrame。"""
    if not records:
        return empty_raw_semiconductor_equipment()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "sales_3mma_raw": [r.billings_raw or _source_string(r.billings_jpy_raw) for r in records],
        "mom_growth_3mma_raw": [r.mom_raw or _source_string(r.mom_reported) for r in records],
        "yoy_growth_3mma_raw": [r.yoy_raw or _source_string(r.yoy_reported) for r in records],
        "source": [r.source or "SEAJ" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }

    return require_raw_release_dates(
        (
            pl.DataFrame(data, schema=SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA)
            .unique(subset=["report_month"], keep="last")
            .sort("trade_date")
        ),
        "semiconductor_equipment",
    )


def empty_semiconductor_equipment() -> pl.DataFrame:
    """构造半导体设备出货空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_EQUIPMENT_SCHEMA)


def records_to_semiconductor_equipment_frame(
    records: Sequence[SemiconductorEquipmentRecord],
    *,
    existing_df: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """将半导体设备出货记录转换为 Curated 表并补算缺失的 3MMA 增速。"""
    if not records:
        return empty_semiconductor_equipment()

    ordered_records = sorted(records, key=lambda record: record.report_month)
    now_iso = datetime.now(UTC).isoformat()
    billings_3mma = [
        _equipment_3mma_billion(
            r.billings_raw or _source_string(r.billings_jpy_raw),
            r.billings_3mma_jpy,
        )
        for r in ordered_records
    ]
    yoy_3mma = [
        _equipment_percent(r.yoy_raw or _source_string(r.yoy_reported), r.yoy_growth_3mma)
        for r in ordered_records
    ]
    mom_3mma = [
        _equipment_percent(r.mom_raw or _source_string(r.mom_reported), r.mom_growth_3mma)
        for r in ordered_records
    ]
    data = {
        "report_month": [r.report_month for r in ordered_records],
        "trade_date": [r.trade_date for r in ordered_records],
        "billings_3mma_jpy": billings_3mma,
        "yoy_growth_3mma": yoy_3mma,
        "mom_growth_3mma": mom_3mma,
        "unit": [r.unit or "billion_jpy" for r in ordered_records],
        "source": [r.source or "SEAJ" for r in ordered_records],
        "source_url": [r.source_url or "" for r in ordered_records],
        "release_date": [r.release_date for r in ordered_records],
        "data_status": [r.data_status or "actual" for r in ordered_records],
        "collected_at": [r.collected_at or now_iso for r in ordered_records],
    }

    new_df = pl.DataFrame(data, schema=SEMICONDUCTOR_EQUIPMENT_SCHEMA)
    if existing_df is not None and not existing_df.is_empty():
        df = pl.concat([existing_df, new_df], how="diagonal_relaxed").select(
            list(SEMICONDUCTOR_EQUIPMENT_SCHEMA)
        )
    else:
        df = new_df
    df = df.unique(subset=["report_month"], keep="last").sort("trade_date")
    return _fill_semiconductor_equipment_growth(df)


def _fill_semiconductor_equipment_growth(df: pl.DataFrame) -> pl.DataFrame:
    """按连续报告月从 SEAJ 3MMA 源值补算缺失的 MoM/YoY。"""
    months = df["report_month"].to_list()
    values = df["billings_3mma_jpy"].to_list()
    mom = df["mom_growth_3mma"].to_list()
    yoy = df["yoy_growth_3mma"].to_list()

    for index, value in enumerate(values):
        if value is None or float(value) <= 0:
            continue
        if (
            mom[index] is None
            and index >= 1
            and _month_lag(months[index - 1], months[index]) == 1
            and values[index - 1] is not None
            and float(values[index - 1]) > 0
        ):
            mom[index] = round(float(value) / float(values[index - 1]) - 1.0, 4)
        if (
            yoy[index] is None
            and index >= 12
            and _month_lag(months[index - 12], months[index]) == 12
            and values[index - 12] is not None
            and float(values[index - 12]) > 0
        ):
            yoy[index] = round(float(value) / float(values[index - 12]) - 1.0, 4)

    return df.with_columns(
        pl.Series("mom_growth_3mma", mom, dtype=pl.Float64),
        pl.Series("yoy_growth_3mma", yoy, dtype=pl.Float64),
    )


def _source_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _equipment_3mma_billion(raw_value: Any, fallback: float | None) -> float | None:
    parsed = _parse_number(raw_value)
    if parsed is not None:
        return round(parsed / 1000.0, 2)
    return round(float(fallback), 2) if fallback is not None else None


def _equipment_percent(raw_value: Any, fallback: float | None) -> float | None:
    parsed = _parse_number(raw_value)
    if parsed is not None:
        value = parsed / 100.0 if raw_value is not None and "%" in str(raw_value) else parsed
        return round(value, 4)
    return round(float(fallback), 4) if fallback is not None else None


def _parse_number(value: object) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", str(value).replace(",", ""))
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _month_lag(left: str, right: str) -> int:
    left_year, left_month = parse_month_string(left)
    right_year, right_month = parse_month_string(right)
    return (right_year * 12 + right_month) - (left_year * 12 + left_month)
