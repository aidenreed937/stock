"""基础化工重点品类供需开工率与价差 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import ChemicalMarketRecord

CHEMICAL_MARKET_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "mdi_operating_rate": pl.Float64,
    "tio2_operating_rate": pl.Float64,
    "refrigerant_r32_operating_rate": pl.Float64,
    "mdi_price_cny": pl.Float64,
    "tio2_price_cny": pl.Float64,
    "mdi_gross_spread_cny": pl.Float64,
    "tio2_spread_cny": pl.Float64,
    "refrigerant_r32_price_cny": pl.Float64,
    "chemical_inventory_days": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_chemical_market() -> pl.DataFrame:
    """构造基础化工市场空事实表骨架。"""
    return pl.DataFrame(schema=CHEMICAL_MARKET_SCHEMA)


def records_to_chemical_market_frame(
    records: Sequence[ChemicalMarketRecord],
) -> pl.DataFrame:
    """将基础化工供需价差记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_chemical_market()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "mdi_operating_rate": [r.mdi_operating_rate for r in records],
        "tio2_operating_rate": [r.tio2_operating_rate for r in records],
        "refrigerant_r32_operating_rate": [r.refrigerant_r32_operating_rate for r in records],
        "mdi_price_cny": [r.mdi_price_cny for r in records],
        "tio2_price_cny": [r.tio2_price_cny for r in records],
        "mdi_gross_spread_cny": [r.mdi_gross_spread_cny for r in records],
        "tio2_spread_cny": [r.tio2_spread_cny for r in records],
        "refrigerant_r32_price_cny": [r.refrigerant_r32_price_cny for r in records],
        "chemical_inventory_days": [r.chemical_inventory_days for r in records],
        "unit": [r.unit or "percent/cny_per_ton" for r in records],
        "source": [r.source or "Baichuan/Zhuochuang" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=CHEMICAL_MARKET_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
