"""农业产业 Curated Schema。"""

import polars as pl

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

__all__ = ["AGRICULTURE_PORK_SCHEMA"]
