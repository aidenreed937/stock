"""煤炭行业动力煤平仓价与电厂库存日耗 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import CoalMarketRecord

COAL_MARKET_SCHEMA = {
    "report_date": pl.String,
    "trade_date": pl.Date,
    "q5500_fob_price_cny": pl.Float64,
    "coking_coal_price_cny": pl.Float64,
    "power_plant_inventory_million_ton": pl.Float64,
    "power_plant_daily_burn_ten_thousand_ton": pl.Float64,
    "power_plant_available_days": pl.Float64,
    "qinhuangdao_inventory_million_ton": pl.Float64,
    "q5500_price_yoy": pl.Float64,
    "q5500_price_mom": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_coal_market() -> pl.DataFrame:
    """构造煤炭市场空事实表骨架。"""
    return pl.DataFrame(schema=COAL_MARKET_SCHEMA)


def records_to_coal_market_frame(
    records: Sequence[CoalMarketRecord],
) -> pl.DataFrame:
    """将煤炭市场记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_coal_market()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_date": [r.report_date for r in records],
        "trade_date": [r.trade_date for r in records],
        "q5500_fob_price_cny": [r.q5500_fob_price_cny for r in records],
        "coking_coal_price_cny": [r.coking_coal_price_cny for r in records],
        "power_plant_inventory_million_ton": [r.power_plant_inventory_million_ton for r in records],
        "power_plant_daily_burn_ten_thousand_ton": [
            r.power_plant_daily_burn_ten_thousand_ton for r in records
        ],
        "power_plant_available_days": [r.power_plant_available_days for r in records],
        "qinhuangdao_inventory_million_ton": [r.qinhuangdao_inventory_million_ton for r in records],
        "q5500_price_yoy": [r.q5500_price_yoy for r in records],
        "q5500_price_mom": [r.q5500_price_mom for r in records],
        "unit": [r.unit or "cny_per_ton/million_tons/days" for r in records],
        "source": [r.source or "CCTD/Sxcoal" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=COAL_MARKET_SCHEMA)
        .unique(subset=["report_date"], keep="last")
        .sort("trade_date")
    )
