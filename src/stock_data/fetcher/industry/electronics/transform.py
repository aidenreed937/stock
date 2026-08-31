"""消费电子终端 (智能手机 / PC / AI 渗透率) Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import ConsumerElectronicsRecord

CONSUMER_ELECTRONICS_SCHEMA = {
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "global_smartphone_shipments_million": pl.Float64,
    "china_smartphone_shipments_million": pl.Float64,
    "global_pc_shipments_million": pl.Float64,
    "ai_phone_penetration_rate": pl.Float64,
    "ai_pc_penetration_rate": pl.Float64,
    "smartphone_yoy_growth": pl.Float64,
    "pc_yoy_growth": pl.Float64,
    "apple_shipments_million": pl.Float64,
    "transsion_shipments_million": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_consumer_electronics() -> pl.DataFrame:
    """构造消费电子空事实表骨架。"""
    return pl.DataFrame(schema=CONSUMER_ELECTRONICS_SCHEMA)


def records_to_consumer_electronics_frame(
    records: Sequence[ConsumerElectronicsRecord],
) -> pl.DataFrame:
    """将消费电子出货记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_consumer_electronics()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_quarter": [r.report_quarter for r in records],
        "trade_date": [r.trade_date for r in records],
        "global_smartphone_shipments_million": [
            r.global_smartphone_shipments_million for r in records
        ],
        "china_smartphone_shipments_million": [
            r.china_smartphone_shipments_million for r in records
        ],
        "global_pc_shipments_million": [r.global_pc_shipments_million for r in records],
        "ai_phone_penetration_rate": [r.ai_phone_penetration_rate for r in records],
        "ai_pc_penetration_rate": [r.ai_pc_penetration_rate for r in records],
        "smartphone_yoy_growth": [r.smartphone_yoy_growth for r in records],
        "pc_yoy_growth": [r.pc_yoy_growth for r in records],
        "apple_shipments_million": [r.apple_shipments_million for r in records],
        "transsion_shipments_million": [r.transsion_shipments_million for r in records],
        "unit": [r.unit or "million_units/percent" for r in records],
        "source": [r.source or "IDC/Canalys" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=CONSUMER_ELECTRONICS_SCHEMA)
        .unique(subset=["report_quarter"], keep="last")
        .sort("trade_date")
    )
