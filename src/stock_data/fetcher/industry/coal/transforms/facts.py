"""煤炭产业黄金事实表转换。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.coal.models import CoalMarketRecord
from stock_data.fetcher.industry.coal.schemas import COAL_MARKET_SCHEMA


def empty_coal_market() -> pl.DataFrame:
    """构造煤炭市场空事实表骨架。"""
    return pl.DataFrame(schema=COAL_MARKET_SCHEMA)


def records_to_coal_market_frame(
    records: Sequence[CoalMarketRecord],
) -> pl.DataFrame:
    """将煤炭市场记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_coal_market()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_date": [r.report_date for r in records],
        "trade_date": [r.trade_date for r in records],
        "q5500_fob_price_cny": [r.q5500_fob_price_cny for r in records],
        "coking_coal_price_cny": [r.coking_coal_price_cny for r in records],
        "power_plant_inventory_million_ton": [r.power_plant_inventory_million_ton for r in records],
        "power_plant_daily_burn_ten_thousand_ton": [
            r.power_plant_daily_burn_ten_thousand_ton for r in records
        ],
        "power_plant_available_days": [r.power_plant_available_days for r in records],
        "qinhuangdao_inventory_million_ton": [r.qinhuangdao_inventory_million_ton for r in records],
        "q5500_price_yoy": [r.q5500_price_yoy for r in records],
        "q5500_price_mom": [r.q5500_price_mom for r in records],
        "unit": [r.unit or "cny_per_ton/million_tons/days" for r in records],
        "source": [r.source or "CCTD/Sxcoal" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=COAL_MARKET_SCHEMA)
        .unique(subset=["report_date"], keep="last")
        .sort("trade_date")
    )


def compute_coal_price_derivatives(
    records: list[CoalMarketRecord],
) -> list[CoalMarketRecord]:
    """计算动力煤平仓价 4 周环比与 52 周同比特征。"""
    updated: list[CoalMarketRecord] = []
    for i, rec in enumerate(records):
        mom: float | None = None
        if (
            i >= 4
            and records[i - 4].q5500_fob_price_cny is not None
            and rec.q5500_fob_price_cny is not None
        ):
            prev_p = records[i - 4].q5500_fob_price_cny
            if prev_p and prev_p > 0:
                mom = round((rec.q5500_fob_price_cny - prev_p) / prev_p, 4)

        yoy: float | None = None
        if (
            i >= 52
            and records[i - 52].q5500_fob_price_cny is not None
            and rec.q5500_fob_price_cny is not None
        ):
            prev_y_p = records[i - 52].q5500_fob_price_cny
            if prev_y_p and prev_y_p > 0:
                yoy = round((rec.q5500_fob_price_cny - prev_y_p) / prev_y_p, 4)

        updated.append(
            CoalMarketRecord(
                report_date=rec.report_date,
                trade_date=rec.trade_date,
                q5500_fob_price_cny=rec.q5500_fob_price_cny,
                coking_coal_price_cny=rec.coking_coal_price_cny,
                power_plant_inventory_million_ton=rec.power_plant_inventory_million_ton,
                power_plant_daily_burn_ten_thousand_ton=rec.power_plant_daily_burn_ten_thousand_ton,
                power_plant_available_days=rec.power_plant_available_days,
                qinhuangdao_inventory_million_ton=rec.qinhuangdao_inventory_million_ton,
                q5500_price_yoy=yoy,
                q5500_price_mom=mom,
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
    "compute_coal_price_derivatives",
    "empty_coal_market",
    "records_to_coal_market_frame",
]
