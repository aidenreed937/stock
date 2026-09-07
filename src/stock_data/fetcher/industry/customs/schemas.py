"""海关贸易 Curated Schema 与存储契约。"""

import polars as pl

CUSTOMS_TRADE_SCHEMA = {
    "category_key": pl.Utf8,
    "category_name": pl.Utf8,
    "product_key": pl.Utf8,
    "product_name": pl.Utf8,
    "hs_code": pl.Utf8,
    "hs_name": pl.Utf8,
    "hs_level": pl.Utf8,
    "hs_parent_code": pl.Utf8,
    "report_month": pl.Utf8,
    "trade_date": pl.Date,
    "trade_direction": pl.Utf8,
    "export_value_usd": pl.Float64,
    "export_volume": pl.Float64,
    "quantity_unit": pl.Utf8,
    "quantity_unit_norm": pl.Utf8,
    "unit_known": pl.Boolean,
    "volume_aggregable": pl.Boolean,
    "export_asp_usd": pl.Float64,
    "target_l1_code": pl.Utf8,
    "target_l1_name": pl.Utf8,
    "target_l2_codes": pl.Utf8,
    "target_l2_names": pl.Utf8,
    "target_l3_codes": pl.Utf8,
    "target_l3_names": pl.Utf8,
    "export_value_3mma": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "source": pl.Utf8,
    "source_url": pl.Utf8,
    "release_date": pl.Date,
    "data_status": pl.Utf8,
    "collected_at": pl.Utf8,
    "trade_value_currency": pl.Utf8,
    "raw_content_sha256": pl.Utf8,
    "raw_snapshot_path": pl.Utf8,
}


__all__ = ["CUSTOMS_TRADE_SCHEMA"]
