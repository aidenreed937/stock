"""航运产业 Curated Schema。"""

import polars as pl

SHIPPING_INDICES_SCHEMA = {
    "trade_date": pl.Date,
    "bdi_index": pl.Float64,
    "bdti_index": pl.Float64,
    "bcti_index": pl.Float64,
    "scfi_index": pl.Float64,
    "bdi_ma200_bias": pl.Float64,
    "bdti_ma200_bias": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

__all__ = ["SHIPPING_INDICES_SCHEMA"]
