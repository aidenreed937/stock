"""农业产业黄金事实表转换。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.agriculture.models import AgriculturePorkRecord
from stock_data.fetcher.industry.agriculture.schemas import AGRICULTURE_PORK_SCHEMA


def empty_agriculture_pork() -> pl.DataFrame:
    """构造生猪养殖数据空事实表骨架。"""
    return pl.DataFrame(schema=AGRICULTURE_PORK_SCHEMA)


def records_to_agriculture_pork_frame(
    records: Sequence[AgriculturePorkRecord],
) -> pl.DataFrame:
    """将生猪养殖记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_agriculture_pork()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "sow_stock_million_heads": [r.sow_stock_million_heads for r in records],
        "sow_stock_yoy": [r.sow_stock_yoy for r in records],
        "sow_stock_mom": [r.sow_stock_mom for r in records],
        "pig_price_cny_per_kg": [r.pig_price_cny_per_kg for r in records],
        "pig_price_yoy": [r.pig_price_yoy for r in records],
        "hog_to_grain_ratio": [r.hog_to_grain_ratio for r in records],
        "pig_farming_profit_cny_head": [r.pig_farming_profit_cny_head for r in records],
        "unit": [r.unit or "million_heads/cny_per_kg" for r in records],
        "source": [r.source or "MARA" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=AGRICULTURE_PORK_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


def compute_pork_derivatives(
    records: list[AgriculturePorkRecord],
) -> list[AgriculturePorkRecord]:
    """计算生猪存栏与价格的环比/同比衍生特征。"""
    updated: list[AgriculturePorkRecord] = []
    for i, rec in enumerate(records):
        sow_mom, sow_yoy, pig_yoy = None, None, None
        if (
            i > 0
            and records[i - 1].sow_stock_million_heads is not None
            and rec.sow_stock_million_heads is not None
        ):
            prev_sow = records[i - 1].sow_stock_million_heads
            if prev_sow and prev_sow > 0:
                sow_mom = round((rec.sow_stock_million_heads - prev_sow) / prev_sow, 4)

        if (
            i >= 12
            and records[i - 12].sow_stock_million_heads is not None
            and rec.sow_stock_million_heads is not None
        ):
            prev_y_sow = records[i - 12].sow_stock_million_heads
            if prev_y_sow and prev_y_sow > 0:
                sow_yoy = round((rec.sow_stock_million_heads - prev_y_sow) / prev_y_sow, 4)

        if (
            i >= 12
            and records[i - 12].pig_price_cny_per_kg is not None
            and rec.pig_price_cny_per_kg is not None
        ):
            prev_y_pig = records[i - 12].pig_price_cny_per_kg
            if prev_y_pig and prev_y_pig > 0:
                pig_yoy = round((rec.pig_price_cny_per_kg - prev_y_pig) / prev_y_pig, 4)

        updated.append(
            AgriculturePorkRecord(
                report_month=rec.report_month,
                trade_date=rec.trade_date,
                sow_stock_million_heads=rec.sow_stock_million_heads,
                sow_stock_yoy=sow_yoy,
                sow_stock_mom=sow_mom,
                pig_price_cny_per_kg=rec.pig_price_cny_per_kg,
                pig_price_yoy=pig_yoy,
                hog_to_grain_ratio=rec.hog_to_grain_ratio,
                pig_farming_profit_cny_head=rec.pig_farming_profit_cny_head,
                unit=rec.unit,
                source=rec.source,
                source_url=rec.source_url,
                release_date=rec.release_date,
                data_status=rec.data_status,
                collected_at=rec.collected_at,
            )
        )
    return updated


__all__ = [
    "compute_pork_derivatives",
    "empty_agriculture_pork",
    "records_to_agriculture_pork_frame",
]
