"""农业农村部 (MARA) 生猪养殖与产能数据 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import AgriculturePorkRecord

AGRICULTURE_PORK_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "sow_stock_million_heads": pl.Float64,
    "sow_stock_yoy": pl.Float64,
    "sow_stock_mom": pl.Float64,
    "pig_price_cny_per_kg": pl.Float64,
    "pig_price_yoy": pl.Float64,
    "hog_to_grain_ratio": pl.Float64,
    "pig_farming_profit_cny_head": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_agriculture_pork() -> pl.DataFrame:
    """构造生猪养殖数据空事实表骨架。"""
    return pl.DataFrame(schema=AGRICULTURE_PORK_SCHEMA)


def records_to_agriculture_pork_frame(
    records: Sequence[AgriculturePorkRecord],
) -> pl.DataFrame:
    """将生猪养殖记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_agriculture_pork()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "sow_stock_million_heads": [r.sow_stock_million_heads for r in records],
        "sow_stock_yoy": [r.sow_stock_yoy for r in records],
        "sow_stock_mom": [r.sow_stock_mom for r in records],
        "pig_price_cny_per_kg": [r.pig_price_cny_per_kg for r in records],
        "pig_price_yoy": [r.pig_price_yoy for r in records],
        "hog_to_grain_ratio": [r.hog_to_grain_ratio for r in records],
        "pig_farming_profit_cny_head": [r.pig_farming_profit_cny_head for r in records],
        "unit": [r.unit or "million_heads/cny_per_kg" for r in records],
        "source": [r.source or "MARA" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=AGRICULTURE_PORK_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
