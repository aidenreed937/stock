"""煤炭产业 Curated Schema。"""

import polars as pl

COAL_MARKET_SCHEMA = {
    "report_date": pl.Date,
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

__all__ = ["COAL_MARKET_SCHEMA"]
