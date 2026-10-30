"""光伏产业链价格 RAW/Curated 转换器。"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

import polars as pl

from stock_data.fetcher.industry.power.models import SolarPriceChainRecord
from stock_data.fetcher.industry.power.schemas import (
    SOLAR_PRICE_CHAIN_RAW_SCHEMA,
    SOLAR_PRICE_CHAIN_SCHEMA,
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


def _parse_report_date(value: str | date) -> date:
    """将价格链报告日期转换为 Curated 的自然日。"""
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def empty_solar_price_chain() -> pl.DataFrame:
    """构造光伏产业链价格空事实表骨架。"""
    return pl.DataFrame(schema=SOLAR_PRICE_CHAIN_SCHEMA)


def records_to_solar_price_chain_frame(
    records: Sequence[SolarPriceChainRecord],
) -> pl.DataFrame:
    """将光伏价格链条记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_solar_price_chain()

    ordered_records = sorted(records, key=lambda record: record.trade_date)
    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_date": [_parse_report_date(r.report_date) for r in ordered_records],
        "trade_date": [r.trade_date for r in ordered_records],
        "polysilicon_price_cny_kg": [
            _raw_number(r.polysilicon_price_cny_kg_raw, r.polysilicon_price_cny_kg)
            for r in ordered_records
        ],
        "wafer_price_cny_piece": [
            _raw_number(r.wafer_price_cny_piece_raw, r.wafer_price_cny_piece)
            for r in ordered_records
        ],
        "cell_price_cny_watt": [
            _raw_number(r.cell_price_cny_watt_raw, r.cell_price_cny_watt) for r in ordered_records
        ],
        "module_price_cny_watt": [
            _raw_number(r.module_price_cny_watt_raw, r.module_price_cny_watt)
            for r in ordered_records
        ],
        "module_price_yoy": [None] * len(ordered_records),
        "module_price_mom": [None] * len(ordered_records),
        "price_cycle_stage": [r.price_cycle_stage for r in ordered_records],
        "unit": [r.unit or "cny_per_unit" for r in ordered_records],
        "source": [r.source or "PVInfoLink/SMM" for r in ordered_records],
        "source_url": [r.source_url or "" for r in ordered_records],
        "release_date": [r.release_date for r in ordered_records],
        "data_status": [r.data_status or "actual" for r in ordered_records],
        "collected_at": [r.collected_at or now_iso for r in ordered_records],
    }

    df = (
        pl.DataFrame(data, schema=SOLAR_PRICE_CHAIN_SCHEMA)
        .unique(subset=["report_date"], keep="last")
        .sort("trade_date")
    )
    return df.with_columns(
        pl.col("price_cycle_stage").forward_fill().alias("price_cycle_stage"),
        pl.when(
            pl.col("module_price_cny_watt").is_not_null()
            & (pl.col("module_price_cny_watt").shift(1) > 0)
        )
        .then(
            (
                pl.col("module_price_cny_watt") / pl.col("module_price_cny_watt").shift(1) - 1.0
            ).round(4)
        )
        .otherwise(None)
        .alias("module_price_mom"),
        pl.when(
            pl.col("module_price_cny_watt").is_not_null()
            & (pl.col("module_price_cny_watt").shift(52) > 0)
        )
        .then(
            (
                pl.col("module_price_cny_watt") / pl.col("module_price_cny_watt").shift(52) - 1.0
            ).round(4)
        )
        .otherwise(None)
        .alias("module_price_yoy"),
    )


def empty_raw_solar_price_chain() -> pl.DataFrame:
    """构造光伏价格链 RAW 空表骨架。"""
    return pl.DataFrame(schema=SOLAR_PRICE_CHAIN_RAW_SCHEMA)


def records_to_raw_solar_price_chain_frame(
    records: Sequence[SolarPriceChainRecord],
) -> pl.DataFrame:
    """将 InfoLink 价格记录转换为只含源端报价的 RAW 表。"""
    if not records:
        return empty_raw_solar_price_chain()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_date": [r.report_date for r in records],
        "trade_date": [r.trade_date for r in records],
        "polysilicon_price_cny_kg_raw": [
            _raw_text(r.polysilicon_price_cny_kg_raw, r.polysilicon_price_cny_kg) for r in records
        ],
        "wafer_price_cny_piece_raw": [
            _raw_text(r.wafer_price_cny_piece_raw, r.wafer_price_cny_piece) for r in records
        ],
        "cell_price_cny_watt_raw": [
            _raw_text(r.cell_price_cny_watt_raw, r.cell_price_cny_watt) for r in records
        ],
        "module_price_cny_watt_raw": [
            _raw_text(r.module_price_cny_watt_raw, r.module_price_cny_watt) for r in records
        ],
        "source": [r.source or "PVInfoLink/SMM" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "raw_content_sha256": [r.raw_content_sha256 or "" for r in records],
        "raw_snapshot_path": [r.raw_snapshot_path or "" for r in records],
    }
    return (
        pl.DataFrame(data, schema=SOLAR_PRICE_CHAIN_RAW_SCHEMA)
        .unique(subset=["report_date"], keep="last")
        .sort("trade_date")
    )


__all__ = [
    "empty_raw_solar_price_chain",
    "empty_solar_price_chain",
    "records_to_raw_solar_price_chain_frame",
    "records_to_solar_price_chain_frame",
]
