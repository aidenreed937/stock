"""有色金属产业 Curated Schema。"""

import polars as pl

NON_FERROUS_METALS_SCHEMA = {
    "report_date": pl.Date,
    "trade_date": pl.Date,
    "lithium_carbonate_price": pl.Float64,
    "shfe_copper_price": pl.Float64,
    "shfe_aluminum_price": pl.Float64,
    "sge_gold_price": pl.Float64,
    "copper_inventory_ton": pl.Float64,
    "copper_ma200_bias": pl.Float64,
    "copper_mom20": pl.Float64,
    "copper_chg60": pl.Float64,
    "lithium_mom20": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

__all__ = ["NON_FERROUS_METALS_SCHEMA"]
