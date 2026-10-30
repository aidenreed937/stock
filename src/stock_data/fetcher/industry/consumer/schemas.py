"""消费产业 Curated Schema。"""

import polars as pl

LIQUOR_WHOLESALE_SCHEMA = {
    "report_date": pl.Date,
    "trade_date": pl.Date,
    "moutai_loose_price_cny": pl.Float64,
    "moutai_boxed_price_cny": pl.Float64,
    "wuliangye_puwu_price_cny": pl.Float64,
    "guojiao1573_price_cny": pl.Float64,
    "moutai_loose_price_yoy": pl.Float64,
    "moutai_loose_price_mom": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

__all__ = ["LIQUOR_WHOLESALE_SCHEMA"]
