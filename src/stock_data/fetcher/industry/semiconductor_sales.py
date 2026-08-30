"""SIA / WSTS 全球半导体月度销售额事实表转换与加载器。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_data.fetcher.industry.models import SemiconductorSalesRecord

SEMICONDUCTOR_SALES_SCHEMA: dict[str, Any] = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "global_sales_usd": pl.Float64,
    "americas_sales_usd": pl.Float64,
    "europe_sales_usd": pl.Float64,
    "japan_sales_usd": pl.Float64,
    "china_sales_usd": pl.Float64,
    "asia_pacific_other_sales_usd": pl.Float64,
    "yoy_growth": pl.Float64,
    "mom_growth": pl.Float64,
}


def empty_semiconductor_sales() -> pl.DataFrame:
    """返回空半导体月度销售额 DataFrame。"""
    return pl.DataFrame(schema=SEMICONDUCTOR_SALES_SCHEMA)


def records_to_semiconductor_frame(records: list[SemiconductorSalesRecord]) -> pl.DataFrame:
    """将半导体记录列表转换为标准化的 Polars DataFrame。"""
    if not records:
        return empty_semiconductor_sales()

    data: dict[str, list[Any]] = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "global_sales_usd": [r.global_sales_usd for r in records],
        "americas_sales_usd": [r.americas_sales_usd for r in records],
        "europe_sales_usd": [r.europe_sales_usd for r in records],
        "japan_sales_usd": [r.japan_sales_usd for r in records],
        "china_sales_usd": [r.china_sales_usd for r in records],
        "asia_pacific_other_sales_usd": [r.asia_pacific_other_sales_usd for r in records],
        "yoy_growth": [r.yoy_growth for r in records],
        "mom_growth": [r.mom_growth for r in records],
    }
    return (
        pl.DataFrame(data, schema=SEMICONDUCTOR_SALES_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
