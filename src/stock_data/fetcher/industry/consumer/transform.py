"""名优白酒周度一批价与动销 Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import LiquorWholesaleRecord

LIQUOR_WHOLESALE_SCHEMA = {
    "report_date": pl.String,
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


def empty_liquor_wholesale() -> pl.DataFrame:
    """构造白酒一批价空事实表骨架。"""
    return pl.DataFrame(schema=LIQUOR_WHOLESALE_SCHEMA)


def records_to_liquor_wholesale_frame(
    records: Sequence[LiquorWholesaleRecord],
) -> pl.DataFrame:
    """将白酒一批价记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_liquor_wholesale()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_date": [r.report_date for r in records],
        "trade_date": [r.trade_date for r in records],
        "moutai_loose_price_cny": [r.moutai_loose_price_cny for r in records],
        "moutai_boxed_price_cny": [r.moutai_boxed_price_cny for r in records],
        "wuliangye_puwu_price_cny": [r.wuliangye_puwu_price_cny for r in records],
        "guojiao1573_price_cny": [r.guojiao1573_price_cny for r in records],
        "moutai_loose_price_yoy": [r.moutai_loose_price_yoy for r in records],
        "moutai_loose_price_mom": [r.moutai_loose_price_mom for r in records],
        "unit": [r.unit or "cny_per_bottle" for r in records],
        "source": [r.source or "TodayLiquorPrice" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=LIQUOR_WHOLESALE_SCHEMA)
        .unique(subset=["report_date"], keep="last")
        .sort("trade_date")
    )
