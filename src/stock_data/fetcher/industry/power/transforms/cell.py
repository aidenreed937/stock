"""国家统计局太阳能电池 RAW/Curated 转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.power.models import SolarCellNbsRecord
from stock_data.fetcher.industry.power.schemas import (
    SOLAR_CELL_NBS_RAW_SCHEMA,
    SOLAR_CELL_NBS_SCHEMA,
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


def empty_solar_cell_nbs() -> pl.DataFrame:
    """构造 NBS 太阳能电池产量空事实表骨架。"""
    return pl.DataFrame(schema=SOLAR_CELL_NBS_SCHEMA)


def records_to_solar_cell_nbs_frame(records: Sequence[SolarCellNbsRecord]) -> pl.DataFrame:
    """将 NBS 太阳能电池月度产量记录转换为强类型 Polars DataFrame。

    1-2 月合并口径若未披露当月值，则保持缺失，不拆分累计值。
    """
    if not records:
        return empty_solar_cell_nbs()

    ordered_records = sorted(records, key=lambda record: record.trade_date)
    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in ordered_records],
        "trade_date": [r.trade_date for r in ordered_records],
        "output_current": [
            _raw_number(r.output_current_raw, r.output_current) for r in ordered_records
        ],
        "output_current_3mma": [None] * len(ordered_records),
        "output_cumulative": [
            _raw_number(r.output_cumulative_raw, r.output_cumulative) for r in ordered_records
        ],
        "output_yoy": [_raw_number(r.output_yoy_raw, r.output_yoy) for r in ordered_records],
        "output_cum_yoy": [
            _raw_number(r.output_cum_yoy_raw, r.output_cum_yoy) for r in ordered_records
        ],
        "yoy_growth_3mma": [None] * len(ordered_records),
        "mom_growth_3mma": [None] * len(ordered_records),
        "unit": [r.unit or "ten_thousand_kw" for r in ordered_records],
        "source": [r.source or "NBS" for r in ordered_records],
        "source_url": [r.source_url or "https://data.stats.gov.cn/" for r in ordered_records],
        "release_date": [r.release_date for r in ordered_records],
        "data_status": [r.data_status or "actual" for r in ordered_records],
        "collected_at": [r.collected_at or now_iso for r in ordered_records],
    }
    df = (
        pl.DataFrame(data, schema=SOLAR_CELL_NBS_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
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
    return df


def empty_raw_solar_cell_nbs() -> pl.DataFrame:
    """构造 NBS 光伏电池产量 RAW 空表骨架。"""
    return pl.DataFrame(schema=SOLAR_CELL_NBS_RAW_SCHEMA)


def records_to_raw_solar_cell_nbs_frame(
    records: Sequence[SolarCellNbsRecord],
) -> pl.DataFrame:
    """将 NBS 光伏电池产量记录转换为只含源端字段的 RAW 表。"""
    if not records:
        return empty_raw_solar_cell_nbs()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "output_current_raw": [_raw_text(r.output_current_raw, r.output_current) for r in records],
        "output_cumulative_raw": [
            _raw_text(r.output_cumulative_raw, r.output_cumulative) for r in records
        ],
        "output_yoy_raw": [_raw_text(r.output_yoy_raw, r.output_yoy) for r in records],
        "output_cum_yoy_raw": [_raw_text(r.output_cum_yoy_raw, r.output_cum_yoy) for r in records],
        "source": [r.source or "NBS" for r in records],
        "source_url": [r.source_url or "https://data.stats.gov.cn/" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }
    return (
        pl.DataFrame(data, schema=SOLAR_CELL_NBS_RAW_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


__all__ = [
    "empty_raw_solar_cell_nbs",
    "empty_solar_cell_nbs",
    "records_to_raw_solar_cell_nbs_frame",
    "records_to_solar_cell_nbs_frame",
]
