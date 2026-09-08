"""新能源汽车产业 RAW/Curated Schema。"""

import polars as pl

NEV_MONTHLY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "wholesale_volume_ten_thousand": pl.Float64,
    "wholesale_volume_3mma": pl.Float64,
    "retail_volume_ten_thousand": pl.Float64,
    "export_volume_ten_thousand": pl.Float64,
    "penetration_rate": pl.Float64,
    "battery_installation_gwh": pl.Float64,
    "yoy_growth": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

NEV_MONTHLY_RAW_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "wholesale_volume_raw": pl.String,
    "total_volume_raw": pl.String,
    "retail_volume_raw": pl.String,
    "export_volume_raw": pl.String,
    "penetration_rate_raw": pl.String,
    "battery_installation_gwh_raw": pl.String,
    "yoy_growth_raw": pl.String,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}


__all__ = ["NEV_MONTHLY_RAW_SCHEMA", "NEV_MONTHLY_SCHEMA"]
