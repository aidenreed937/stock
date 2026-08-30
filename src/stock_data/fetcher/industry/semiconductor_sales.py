"""全球半导体月度销售额 (SIA/WSTS) Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import SemiconductorSalesRecord

SEMICONDUCTOR_SALES_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "global_sales_usd": pl.Float64,
    "china_sales_usd": pl.Float64,
    "china_yoy_growth": pl.Float64,
    "china_mom_growth": pl.Float64,
    "americas_sales_usd": pl.Float64,
    "europe_sales_usd": pl.Float64,
    "japan_sales_usd": pl.Float64,
    "asia_pacific_other_sales_usd": pl.Float64,
    "yoy_growth": pl.Float64,
    "mom_growth": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_semiconductor_sales() -> pl.DataFrame:
    """构造空事实表骨架。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_SALES_SCHEMA)


def records_to_semiconductor_frame(
    records: Sequence[SemiconductorSalesRecord],
) -> pl.DataFrame:
    """将半导体销售额记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_semiconductor_sales()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "global_sales_usd": [r.global_sales_usd for r in records],
        "china_sales_usd": [r.china_sales_usd for r in records],
        "china_yoy_growth": [r.china_yoy_growth for r in records],
        "china_mom_growth": [r.china_mom_growth for r in records],
        "americas_sales_usd": [r.americas_sales_usd for r in records],
        "europe_sales_usd": [r.europe_sales_usd for r in records],
        "japan_sales_usd": [r.japan_sales_usd for r in records],
        "asia_pacific_other_sales_usd": [r.asia_pacific_other_sales_usd for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "mom_growth": [r.mom_growth for r in records],
        "unit": [r.unit or "billion_usd" for r in records],
        "source": [r.source or "SIA/WSTS" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }
    return (
        pl.DataFrame(data, schema=SEMICONDUCTOR_SALES_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
