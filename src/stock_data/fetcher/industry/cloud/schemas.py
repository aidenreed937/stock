"""云计算产业 CapEx 的 RAW/Curated Schema。"""

import polars as pl

CLOUD_CAPEX_RAW_SCHEMA = {
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "msft_capex_raw": pl.String,
    "goog_capex_raw": pl.String,
    "meta_capex_raw": pl.String,
    "amzn_capex_raw": pl.String,
    "msft_release_date": pl.Date,
    "goog_release_date": pl.Date,
    "meta_release_date": pl.Date,
    "amzn_release_date": pl.Date,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

CLOUD_CAPEX_CURATED_SCHEMA = {
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "total_capex_billion_usd": pl.Float64,
    "msft_capex_billion_usd": pl.Float64,
    "goog_capex_billion_usd": pl.Float64,
    "meta_capex_billion_usd": pl.Float64,
    "amzn_capex_billion_usd": pl.Float64,
    "yoy_growth": pl.Float64,
    "qoq_growth": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

# 兼容现有调用方：CLOUD_CAPEX_SCHEMA 表示 Curated 输出 Schema。
CLOUD_CAPEX_SCHEMA = CLOUD_CAPEX_CURATED_SCHEMA

__all__ = [
    "CLOUD_CAPEX_CURATED_SCHEMA",
    "CLOUD_CAPEX_RAW_SCHEMA",
    "CLOUD_CAPEX_SCHEMA",
]
